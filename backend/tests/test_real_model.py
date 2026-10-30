"""REAL MODEL: the actual downloaded checkpoint (checkpoints/r2_e3b_positive) through the API.

These tests load the frozen mBERT detector once (see conftest.real_model) and are skipped
when the checkpoint or the confidentiality_detector package is not available. Texts are
synthetic. Expected values were observed with the frozen checkpoint on CPU.

Language scope: the model was fine-tuned on English data only. English tests check its
detections; Arabic tests check that the Saudi rules still mask Saudi values whatever the
model predicts. They do not show that the model supports Arabic.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from backend.app.detection import CombinedDetector, DetectionFailedError
from backend.app.errors import DETECTION_FAILED
from backend.app.labels import MODEL_LABEL_TO_CODE
from backend.app.main import build_detector, create_app
from backend.app.saudi_rules import SaudiRuleDetector
from backend.tests.conftest import assert_error

pytestmark = pytest.mark.real_model

HANDOFF_SAMPLE = "Hi, please log in as jdoe with password Zq81kLm!x and call Mira Okafor on 555-0142."
CONTRACT_SAMPLE = "Summarize the complaint from customer Ahmed Alotaibi, ID 1098765432, about invoice #4471."


@pytest.fixture
def client(settings, real_model):
    return TestClient(create_app(settings, detector=CombinedDetector(real_model, SaudiRuleDetector())))


def check(client, text):
    response = client.post("/api/check", json={"text": text})
    assert response.status_code == 200
    return response.json()


def direct(real_model, text):
    """The frozen detector's own answer, without the backend."""
    return real_model._inspector.inspect(text, "strict")


# ---------- English: what the model was trained for ----------

@pytest.mark.parametrize("text", [
    "Please summarise the attached meeting notes for the team.",
    "Draft a polite reply to a customer asking about a delayed refund.",
])
def test_clean_english_text_is_allowed_unchanged(client, text):
    body = check(client, text)
    assert (body["decision"], body["reason"], body["safe_text"], body["detected"], body["spans"]) == (
        "ALLOW", "No sensitive data found", text, [], [])


def test_english_sensitive_text_is_blocked_with_a_masked_copy(client):
    body = check(client, HANDOFF_SAMPLE)
    assert body["decision"] == "BLOCK"
    assert body["reason"] == "Sensitive data found, masked copy returned"
    assert body["safe_text"] == (
        "Hi, please log in as [USERNAME] with password [PASSWORD] and call [PERSON_NAME] [PERSON_NAME] on [PHONE].")
    assert [HANDOFF_SAMPLE[s["start"]:s["end"]] for s in body["spans"]] == [
        "jdoe", "Zq81kLm!x", "Mira", "Okafor", "555-0142"]
    assert [s["type"] for s in body["spans"]] == ["USERNAME", "PASSWORD", "PERSON_NAME", "PERSON_NAME", "PHONE"]


def test_email_iban_and_names(client):
    text = "Contact Sara Lopez at sara.lopez@example.com, IBAN DE89370400440532013000."
    body = check(client, text)
    assert body["safe_text"] == "Contact [PERSON_NAME] [PERSON_NAME] at [EMAIL], IBAN [IBAN]."
    assert body["detected"] == [
        {"type": "PERSON_NAME", "label": "Person name", "count": 2},
        {"type": "EMAIL", "label": "Email address", "count": 1},
        {"type": "IBAN", "label": "IBAN", "count": 1},
    ]


def test_us_ssn_is_its_own_type(client):
    assert check(client, "SSN 123-45-6789 for the tax form.")["safe_text"] == "SSN [SSN] for the tax form."


@pytest.mark.parametrize("text", [HANDOFF_SAMPLE, "Contact Sara Lopez at sara.lopez@example.com.",
                                  "Please summarise the attached meeting notes for the team."])
def test_api_matches_direct_inference(client, real_model, text):
    # docs/INTEGRATION.md §7: same decision and the same (start, end, type) as the frozen detector.
    expected = direct(real_model, text)
    body = check(client, text)
    assert body["decision"] == expected.decision
    assert [(s["start"], s["end"], s["type"]) for s in body["spans"]] == [
        (f.start, f.end, MODEL_LABEL_TO_CODE[f.label]) for f in expected.findings]


# ---------- the full system closes gaps of the Saudi rules alone ----------

@pytest.mark.parametrize("text, expected", [
    ("email: ali@company.sa.", "email: [EMAIL]."),
    ("Call +966 5 5123 4567", "Call [PHONE]"),
])
def test_rules_v3_catch_what_the_saudi_rules_miss(client, text, expected):
    assert check(client, text)["safe_text"] == expected


# ---------- Saudi values: the Saudi rules add what the model misses; the model's types are kept ----------

def test_contract_sample_keeps_the_model_type_for_the_id(client, real_model):
    model_labels = {CONTRACT_SAMPLE[f.start:f.end]: f.label for f in direct(real_model, CONTRACT_SAMPLE).findings}
    assert model_labels["1098765432"] == "ACCOUNTNUMBER"  # the English model's guess for a Saudi ID

    # The Saudi national ID rule matches the same value; it is masked once, with the core type.
    body = check(client, CONTRACT_SAMPLE)
    assert body["decision"] == "BLOCK"
    assert body["safe_text"] == (
        "Summarize the complaint from customer [PERSON_NAME] [PERSON_NAME], ID [ACCOUNT_NUMBER], about invoice #4471.")
    assert body["detected"] == [
        {"type": "PERSON_NAME", "label": "Person name", "count": 2},
        {"type": "ACCOUNT_NUMBER", "label": "Account number", "count": 1},
    ]


def test_arabic_indic_phone_missed_by_the_model_is_masked_by_the_saudi_rules(client, real_model):
    text = "رقم الهاتف: ٠٥٥١٢٣٤٥٦٧"
    assert direct(real_model, text).decision == "ALLOW"  # the model alone misses it
    body = check(client, text)
    assert body["decision"] == "BLOCK"
    assert body["safe_text"] == "رقم الهاتف: [PHONE]"


def test_arabic_text_saudi_values_are_masked_with_the_model_types(client):
    # The model flags the ID and the phone number as ACCOUNTNUMBER; the Saudi rules match the
    # same values, so they are masked once and keep the model's type.
    text = "العميل أحمد العتيبي رقم الهوية 1098765432 وجواله 0551234567 وبريده test@example.com"
    body = check(client, text)
    types = {d["type"] for d in body["detected"]}
    assert body["decision"] == "BLOCK"
    assert types == {"PERSON_NAME", "ACCOUNT_NUMBER", "EMAIL"}
    for value in ("1098765432", "0551234567", "test@example.com"):
        assert value not in body["safe_text"]
    # Model findings that cut a word are widened, so no fragment like "ال[PERSON_NAME]" remains.
    assert "ال[" not in body["safe_text"]


def test_id_attached_to_an_arabic_word_is_masked_completely(client):
    # The Saudi rules miss this (see test_saudi_rules); the model flags part of it, which
    # previously left "10" of the ID visible. The whole word is masked now.
    body = check(client, "هويتي1098765432")
    assert body["decision"] == "BLOCK"
    assert body["safe_text"] == "[ACCOUNT_NUMBER]"


def test_clean_arabic_sentence(client):
    # One harmless sentence, not evidence of Arabic support by the model.
    text = "السلام عليكم كيف الحال؟"
    assert check(client, text)["safe_text"] == text


# ---------- failures with the real model never become a successful scan ----------

def test_text_over_the_detector_limit_is_a_failure(real_model):
    # The frozen detector answers INPUT_TOO_LARGE above 100,000 characters (the API itself
    # accepts at most 10,000, so this is checked on the adapter).
    with pytest.raises(DetectionFailedError):
        real_model.detect("a" * 100_001)


def test_inference_error_inside_the_real_pipeline_answers_503(client, real_model, monkeypatch):
    def crash(texts):
        raise RuntimeError("simulated inference failure")

    monkeypatch.setattr(real_model._inspector.model_detector, "token_predictions", crash)
    response = client.post("/api/check", json={"text": HANDOFF_SAMPLE})
    assert assert_error(response, 503) == DETECTION_FAILED
    assert client.get("/api/stats").json()["total"] == 0


# ---------- privacy with real detections ----------

def test_nothing_sensitive_is_logged_or_stored(client, settings, caplog):
    with caplog.at_level(logging.DEBUG):
        body = check(client, HANDOFF_SAMPLE)
    raw = b"".join(p.read_bytes() for p in settings.db_path.parent.glob("washq.sqlite3*"))
    for value in ("jdoe", "Zq81kLm!x", "Mira", "Okafor", "555-0142", HANDOFF_SAMPLE, body["safe_text"]):
        assert value not in caplog.text
        assert value.encode() not in raw
    assert "decision=BLOCK" in caplog.text  # the frozen detector's own log line: metadata only


# ---------- start-up with the real checkpoint ----------

def test_app_start_up_loads_the_real_detector(settings):
    with TestClient(create_app(settings, detector_factory=build_detector)) as client:
        assert isinstance(client.app.state.detector, CombinedDetector)
        assert client.get("/health").json() == {"status": "ready", "model_loaded": True}
        body = check(client, CONTRACT_SAMPLE)
        assert body["decision"] == "BLOCK" and "[ACCOUNT_NUMBER]" in body["safe_text"]
        # The Saudi extension is part of the started detector: it masks a phone number the model misses.
        assert check(client, "رقم الهاتف: ٠٥٥١٢٣٤٥٦٧")["safe_text"] == "رقم الهاتف: [PHONE]"
