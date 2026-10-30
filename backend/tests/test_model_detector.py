"""The model adapter, the combined detector and start-up, with MOCKED model results.

No checkpoint is loaded here: FakeInspector stands in for the frozen ConfidentialityDetector
and returns its real Decision/Finding types. The real model is tested in test_real_model.py.
"""

import logging
import threading
import time

import pytest
from confidentiality_detector.policy import Decision, Finding
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import Settings
from backend.app.detection import CombinedDetector, DetectionFailedError, Entity
from backend.app.detector_stub import UnavailableDetector
from backend.app.errors import DETECTION_FAILED, DETECTION_UNAVAILABLE
from backend.app.main import build_detector, create_app, load_detector
from backend.app.model_detector import ModelDetector
from backend.app.saudi_rules import SaudiRuleDetector
from backend.tests.conftest import SECRET, FakeDetector, assert_error


def blocked(*findings):
    return Decision("BLOCK", "SENSITIVE_ENTITIES", "strict", tuple(sorted({f.label for f in findings})), findings)


ALLOWED = Decision("ALLOW", "NO_SENSITIVE_ENTITIES", "strict", ())


def special(reason, decision="BLOCK"):
    return Decision(decision, reason, "strict", ())


class FakeInspector:
    def __init__(self, result=None, error=None, delay=0.0):
        self.result, self.error, self.delay = result, error, delay
        self.modes = []
        self.active = self.max_active = 0
        self._count_lock = threading.Lock()

    def inspect(self, text, mode=None):
        with self._count_lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.modes.append(mode)
            time.sleep(self.delay)
            if self.error:
                raise self.error
            return self.result
        finally:
            with self._count_lock:
                self.active -= 1


# ---------- ModelDetector ----------

def test_findings_become_entities_with_the_model_labels():
    inspector = FakeInspector(blocked(Finding(0, 5, "FIRSTNAME", "model", 0.99), Finding(10, 18, "PASSWORD", "model+rules", 1.0)))
    assert ModelDetector(inspector).detect("x" * 20) == [Entity(0, 5, "FIRSTNAME"), Entity(10, 18, "PASSWORD")]


def test_clean_result_has_no_entities():
    assert ModelDetector(FakeInspector(ALLOWED)).detect("hello") == []


def test_mode_is_always_strict():
    inspector = FakeInspector(ALLOWED)
    detector = ModelDetector(inspector)
    detector.detect("a")
    detector.detect("b")
    assert inspector.modes == ["strict", "strict"]


@pytest.mark.parametrize(
    "result",
    [
        special("INSPECTION_ERROR"),
        special("INPUT_TOO_LARGE"),
        special("EMPTY_INPUT", "ALLOW"),
        Decision("BLOCK", "SENSITIVE_ENTITIES", "strict", ()),  # BLOCK without findings: nothing to mask
        Decision("ALLOW", "NO_SENSITIVE_ENTITIES", "strict", (), (Finding(0, 2, "EMAIL", "rules"),)),
        Decision("ALLOW", "SENSITIVE_ENTITIES", "strict", ("EMAIL",), (Finding(0, 2, "EMAIL", "rules"),)),
        Decision("BLOCK", "SOMETHING_NEW", "strict", ()),
    ],
    ids=["inspection-error", "input-too-large", "empty-input", "block-without-findings",
         "allow-with-findings", "decision-reason-mismatch", "unknown-reason"],
)
def test_anything_but_a_completed_inspection_is_a_failure(result):
    with pytest.raises(DetectionFailedError):
        ModelDetector(FakeInspector(result)).detect("some text")


def test_inference_calls_are_serialised():
    inspector = FakeInspector(ALLOWED, delay=0.02)
    detector = ModelDetector(inspector)
    threads = [threading.Thread(target=detector.detect, args=("text",)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(inspector.modes) == 8
    assert inspector.max_active == 1


# ---------- through the API: failures never become a successful scan ----------

@pytest.mark.parametrize(
    "inspector",
    [FakeInspector(special("INSPECTION_ERROR")), FakeInspector(special("INPUT_TOO_LARGE")),
     FakeInspector(error=RuntimeError(f"inference crashed on {SECRET}"))],
    ids=["inspection-error", "input-too-large", "inspector-raises"],
)
def test_model_failures_answer_503_and_record_nothing(make_client, inspector, caplog):
    client = make_client(detector=CombinedDetector(ModelDetector(inspector), SaudiRuleDetector()))
    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/check", json={"text": f"call 0551234567 {SECRET}"})
    assert assert_error(response, 503) == DETECTION_FAILED
    assert client.get("/api/stats").json()["total"] == 0
    assert SECRET not in response.text and SECRET not in caplog.text


# ---------- CombinedDetector: model + Saudi rules ----------

def test_combined_returns_entities_of_all_detectors():
    combined = CombinedDetector(FakeDetector(("Ahmed", "FIRSTNAME")), SaudiRuleDetector())
    assert combined.detect("Ahmed 0551234567") == [Entity(0, 5, "FIRSTNAME"), Entity(6, 16, "private_phone")]


def test_if_the_model_fails_the_saudi_rules_alone_do_not_answer():
    # A partial result could miss names, passwords, ... that only the model finds.
    combined = CombinedDetector(FakeDetector(error=RuntimeError()), SaudiRuleDetector())
    with pytest.raises(RuntimeError):
        combined.detect("call 0551234567")


def test_model_label_is_kept_when_a_saudi_rule_matches_the_same_id(make_client):
    text = "Customer Ahmed Alotaibi, ID 1098765432."
    model = ModelDetector(FakeInspector(blocked(
        Finding(9, 14, "FIRSTNAME", "model"), Finding(15, 23, "LASTNAME", "model"), Finding(28, 38, "ACCOUNTNUMBER", "model"))))
    body = make_client(detector=CombinedDetector(model, SaudiRuleDetector())).post("/api/check", json={"text": text}).json()
    assert body["decision"] == "BLOCK"
    assert body["safe_text"] == "Customer [PERSON_NAME] [PERSON_NAME], ID [ACCOUNT_NUMBER]."
    assert body["detected"] == [
        {"type": "PERSON_NAME", "label": "Person name", "count": 2},
        {"type": "ACCOUNT_NUMBER", "label": "Account number", "count": 1},
    ]


def test_saudi_rules_still_find_values_the_model_misses(make_client):
    text = "رقم الهاتف: ٠٥٥١٢٣٤٥٦٧ ورقم الإقامة 2123456789"
    combined = CombinedDetector(ModelDetector(FakeInspector(ALLOWED)), SaudiRuleDetector())
    body = make_client(detector=combined).post("/api/check", json={"text": text}).json()
    assert body["decision"] == "BLOCK"
    assert body["safe_text"] == "رقم الهاتف: [PHONE] ورقم الإقامة [IQAMA]"


def test_same_value_found_by_both_is_masked_once(make_client):
    text = "mail test@example.com now"
    model = ModelDetector(FakeInspector(blocked(Finding(5, 21, "EMAIL", "model+rules"))))
    body = make_client(detector=CombinedDetector(model, SaudiRuleDetector())).post("/api/check", json={"text": text}).json()
    assert body["safe_text"] == "mail [EMAIL] now"
    assert body["detected"] == [{"type": "EMAIL", "label": "Email address", "count": 1}]
    assert body["spans"] == [{"start": 5, "end": 21, "type": "EMAIL"}]


def test_clean_text_from_both_is_allowed_unchanged(make_client):
    text = "Please summarise the attached meeting notes for the team."
    combined = CombinedDetector(ModelDetector(FakeInspector(ALLOWED)), SaudiRuleDetector())
    body = make_client(detector=combined).post("/api/check", json={"text": text}).json()
    assert (body["decision"], body["safe_text"], body["detected"], body["spans"]) == ("ALLOW", text, [], [])


# ---------- start-up ----------

def test_importing_the_app_does_not_load_the_model():
    # Before start-up the running app has no detector, so a scan could only answer 503.
    assert isinstance(main.app.state.detector, UnavailableDetector)


def test_failed_load_keeps_scans_unavailable(settings, caplog):
    def broken_factory(settings):
        raise FileNotFoundError("model.safetensors is missing")

    with caplog.at_level(logging.ERROR), TestClient(create_app(settings, detector_factory=broken_factory)) as client:
        health = client.get("/health")
        assert (health.status_code, health.json()) == (503, {"status": "not_ready", "model_loaded": False})
        assert "safetensors" not in health.text  # no file names or error contents
        response = client.post("/api/check", json={"text": "Please summarise the notes."})
        assert assert_error(response, 503) == DETECTION_UNAVAILABLE
        assert client.get("/api/stats").json()["total"] == 0
    assert "FileNotFoundError" in caplog.text


def test_successful_load_is_used(settings):
    detector = FakeDetector()
    with TestClient(create_app(settings, detector_factory=lambda s: detector)) as client:
        assert client.get("/health").json() == {"status": "ready", "model_loaded": True}
        assert client.post("/api/check", json={"text": "hello"}).json()["decision"] == "ALLOW"
    assert detector.calls == 1


def test_missing_checkpoint_folder_gives_an_unavailable_detector(tmp_path, caplog):
    settings = Settings(db_path=tmp_path / "db.sqlite3", model_dir=tmp_path / "no-such-checkpoint")
    with caplog.at_level(logging.ERROR):
        assert isinstance(load_detector(build_detector, settings), UnavailableDetector)
    assert "checkpoint folder not found" in caplog.text


def test_missing_policy_file_gives_an_unavailable_detector(tmp_path, caplog):
    settings = Settings(db_path=tmp_path / "db.sqlite3", model_dir=tmp_path, policy_path=tmp_path / "policy.json")
    with caplog.at_level(logging.ERROR):
        assert isinstance(load_detector(build_detector, settings), UnavailableDetector)
    assert "policy file not found" in caplog.text


def test_settings_read_the_model_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("WASHQ_MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.setenv("WASHQ_POLICY_PATH", str(tmp_path / "policy.json"))
    monkeypatch.setenv("WASHQ_DEVICE", "cpu")
    settings = Settings()
    assert (settings.model_dir, settings.policy_path, settings.device) == (tmp_path / "model", tmp_path / "policy.json", "cpu")


def test_default_paths_point_at_the_repository_checkpoint(monkeypatch):
    for name in ("WASHQ_MODEL_DIR", "WASHQ_POLICY_PATH", "WASHQ_DEVICE"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.model_dir.parts[-2:] == ("checkpoints", "r2_e3b_positive")
    assert settings.policy_path.parts[-3:] == ("configs", "inference", "policy.json")
    assert settings.device == "cpu"
