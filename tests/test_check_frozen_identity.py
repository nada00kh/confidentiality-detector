import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import challenge_v2 as cv2  # noqa: E402
import check_frozen_identity as cfi  # noqa: E402

POLICY = ROOT / "configs/inference/policy.json"


@pytest.fixture
def frozen_copy(tmp_path, monkeypatch):
    """A fake checkpoint and a frozen record of it (and of this checkout's code and runtime)."""
    model = tmp_path / "ckpt"
    model.mkdir()
    (model / "model.safetensors").write_bytes(b"weights")
    (model / "config.json").write_text("{}", encoding="utf-8")
    record = tmp_path / "frozen_system.json"
    monkeypatch.setattr(cfi, "FROZEN", record)

    def freeze(**changes):
        record.write_text(json.dumps({**cv2.system_fingerprint(model, POLICY), **changes}), encoding="utf-8")
        return record

    freeze()
    return model, freeze


def test_an_exact_copy_matches(frozen_copy):
    model, _ = frozen_copy
    r = cfi.compare(model, POLICY)
    assert not any(r["parts"].values()) and r["line_endings_differ"] == [] and r["runtime_differs"] == {}


def test_extra_missing_or_changed_checkpoint_files_are_reported(frozen_copy):
    model, _ = frozen_copy
    (model / "desktop.ini").write_text("[.ShellClassInfo]", encoding="utf-8")  # e.g. added by a cloud-drive client
    (model / "model.safetensors").write_bytes(b"other weights")
    (model / "config.json").unlink()
    problem = cfi.compare(model, POLICY)["parts"]["checkpoint files"]
    assert problem == "missing: config.json; not in the frozen record: desktop.ini; sha256 differs: model.safetensors"


def test_line_endings_are_told_apart_from_code_changes(frozen_copy):
    model, freeze = frozen_copy
    code = dict(cv2.system_fingerprint(model, POLICY)["code_sha256"])
    other_endings = (cfi.PACKAGE / "pipeline.py").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    if hashlib.sha256(other_endings).hexdigest() == code["pipeline.py"]:  # the file already has CRLF endings
        other_endings = other_endings.replace(b"\r\n", b"\n")
    freeze(code_sha256={**code, "pipeline.py": hashlib.sha256(other_endings).hexdigest(), "policy.py": "0" * 64},
           runtime={**cv2.system_fingerprint(model, POLICY)["runtime"], "python": "3.13.0-frozen"})
    r = cfi.compare(model, POLICY)
    assert r["line_endings_differ"] == ["pipeline.py"] and r["parts"]["inference code"] == "content differs: policy.py"
    assert r["runtime_differs"]["python"]["frozen"] == "3.13.0-frozen"


FROZEN_CHECKPOINT = ROOT / "checkpoints/r2_e3b_positive"


@pytest.mark.skipif(not (FROZEN_CHECKPOINT / "model.safetensors").exists(), reason="frozen checkpoint not available locally")
def test_the_local_checkpoint_is_the_frozen_detector():
    r = cfi.compare(FROZEN_CHECKPOINT, POLICY)
    assert not any(r["parts"].values()), r["parts"]
