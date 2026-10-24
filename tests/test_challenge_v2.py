import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import challenge_v2 as cv2  # noqa: E402

from confidentiality_detector.challenge import load_challenge  # noqa: E402
from confidentiality_detector.documents import Span  # noqa: E402

SECRET = "Zq!81kLm"
CASES = f"""# hidden challenge v2 (test fixture)
@@ c-001 | enterprise,difficult-positive | BLOCK
please reset the vpn account, temporary password [[PASSWORD:{SECRET}]] expires tonight

@@ c-002 | lookalike | ALLOW
the tracking number [[!TRACKING:1Z999AA10123456784]] has not moved since monday

@@ c-003 | structured | BLOCK
{{"card": "[[CREDITCARDNUMBER:4111 1111 1111 1111]]", "exp": "09/28", "cvc": "[[CREDITCARDCVV:737]]"}}

@@ c-004 | lookalike,unfamiliar-format | AMBIGUOUS
the sticky note just says [[~AMBIG:482]]

@@ c-005 | long | ALLOW
{"Quarterly planning notes without any personal data. " * 40}
"""


@pytest.fixture
def challenge(tmp_path, monkeypatch):
    path = tmp_path / "challenge_v2.txt"
    path.write_text(CASES, encoding="utf-8")
    monkeypatch.setattr(cv2, "STATE", tmp_path / "state")
    return path


def test_validate_reports_aggregates_and_policy_warnings(challenge):
    r = cv2.validate(challenge)
    assert r["ok"] and r["n_cases"] == 5 and r["decisions"] == {"BLOCK": 2, "ALLOW": 2, "AMBIGUOUS": 1}
    assert any("only 2 BLOCK cases" in w for w in r["warnings"])  # below the recommended size
    assert SECRET not in json.dumps(r)


def test_validate_flags_cvv_without_evidence_and_missing_decision(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("@@ x-1 | lookalike | BLOCK\nmy number is [[CREDITCARDCVV:482]]\n\n@@ x-2 | enterprise\nhello\n", encoding="utf-8")
    r = cv2.validate(p)
    assert not r["ok"] and any("missing document decision" in e for e in r["errors"])
    assert any("CVV without contextual evidence" in w for w in r["warnings"])


def test_inconsistent_decision_is_a_parse_error(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("@@ x-1 | lookalike | ALLOW\nmail [[EMAIL:a@b.example]]\n", encoding="utf-8")
    assert not cv2.validate(p)["ok"]


def test_seal_and_tamper_detection(challenge):
    cv2.seal(challenge)
    assert cv2.check_sealed(challenge)["n_cases"] == 5
    challenge.write_text(CASES.replace("monday", "tuesday"), encoding="utf-8")
    with pytest.raises(SystemExit, match="does not match the sealed"):
        cv2.check_sealed(challenge)


def test_score_uses_system_decisions_and_never_contains_text(challenge):
    docs = load_challenge(challenge)
    by_id = {d.doc_id: d for d in docs}
    findings = {d.doc_id: [] for d in docs}
    pw = by_id["c-001"].spans[0]
    findings["c-001"] = [Span(pw.start, pw.end, "PASSWORD")]
    decisions = {"c-001": True, "c-002": True, "c-003": False, "c-004": False, "c-005": False}
    r = cv2.score(docs, findings, decisions)
    assert r["document"]["confusion"] == {"TP_block": 1, "FN_false_allow": 1, "FP_false_block": 1, "TN_allow": 1}
    assert r["document"]["n_ambiguous_excluded"] == 1
    assert r["block_docs_with_every_entity_caught"] == 0.5
    details = cv2.case_details(docs, findings, decisions)
    blob = json.dumps(r) + json.dumps(details)
    for text in (SECRET, "4111", "tracking number", "Quarterly"):
        assert text not in blob


def test_empty_or_headerless_file_cannot_be_sealed(tmp_path, monkeypatch):
    monkeypatch.setattr(cv2, "STATE", tmp_path / "state")
    p = tmp_path / "empty.txt"
    p.write_text("x\n", encoding="utf-8")
    assert not cv2.validate(p)["ok"]
    with pytest.raises(SystemExit, match="cannot seal"):
        cv2.seal(p)


# --- decision F: out-of-scope credentials count against the detector ---------------------

APIKEY_CASES = """@@ k-001 | structured,oos-secret | ALLOW
export STRIPE_KEY=[[!APIKEY:sk_test_4eC39HqLyjWDarjtT1zdp7dc]]

@@ k-002 | structured,oos-secret | BLOCK
db password [[PASSWORD:Ord3rs!Prod]] and api key [[!APIKEY:sk_test_4eC39HqLyjWDarjtT1zdp7dc]]
"""


def test_api_key_predicted_as_password_is_a_false_positive_and_a_false_block(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text(APIKEY_CASES, encoding="utf-8")
    docs = {d.doc_id: d for d in load_challenge(p)}
    key1, key2 = docs["k-001"].negative_spans[0], docs["k-002"].negative_spans[0]
    pw = docs["k-002"].spans[0]
    findings = {"k-001": [Span(key1.start, key1.end, "PASSWORD")],
                "k-002": [Span(pw.start, pw.end, "PASSWORD"), Span(key2.start, key2.end, "PASSWORD")]}
    r = cv2.score(list(docs.values()), findings, {"k-001": True, "k-002": True})
    assert r["document"]["confusion"]["FP_false_block"] == 1 and r["document"]["n_ambiguous_excluded"] == 0
    assert r["entity_micro"]["fp"] == 2 and r["fp_breakdown"].get("hard_negative") == 2
    assert set(r["by_length"]) == {"<=1000 chars"}


def test_ignoring_an_out_of_scope_credential_is_a_validation_error(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("@@ k-1 | oos-secret | AMBIGUOUS\nexport AWS_SECRET_ACCESS_KEY=[[~SECRET:wJalrXUtnFEMI/K7MDENGbPxRfiCYEXAMPLE]]\n",
                 encoding="utf-8")
    r = cv2.validate(p)
    assert not r["ok"] and any("decision F" in e for e in r["errors"])


def test_overlay_can_turn_an_ignored_secret_into_an_out_of_scope_negative(tmp_path):
    from confidentiality_detector.challenge import apply_overlay
    from confidentiality_detector.metrics import evaluate

    src = tmp_path / "c.txt"
    src.write_text("@@ code-1 | code\nexport AWS_SECRET_ACCESS_KEY=[[~SECRET:wJalrXUtnFEMIEXAMPLE]]\n", encoding="utf-8")
    overlay = tmp_path / "o.json"
    overlay.write_text(json.dumps({"applies_to_sha256": cv2.sha256(src), "changes": {
        "code-1": {"ignore_to_negative": {"wJalrXUtnFEMIEXAMPLE": "APIKEY"}, "reason": "decision F"}}}), encoding="utf-8")
    before = load_challenge(src)
    after = apply_overlay(before, overlay, src)
    assert before[0].gold_decision() == "AMBIGUOUS" and after[0].gold_decision() == "ALLOW"
    assert [n.label for n in after[0].negative_spans] == ["APIKEY"] and not after[0].ignore_spans
    neg = after[0].negative_spans[0]
    r = evaluate(after, {"code-1": [Span(neg.start, neg.end, "PASSWORD")]})
    assert r["document"]["confusion"]["FP_false_block"] == 1 and r["entity"]["micro"]["fp"] == 1
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"applies_to_sha256": cv2.sha256(src), "changes": {
        "code-1": {"ignore_to_negative": {"not-there": "APIKEY"}}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="not found as ignore spans"):
        apply_overlay(before, bad, src)


def test_evaluation_refuses_a_system_that_is_not_the_frozen_one(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setattr(cv2, "FROZEN", tmp_path / "frozen_system.json")
    model = tmp_path / "ckpt"
    model.mkdir()
    (model / "model.safetensors").write_bytes(b"weights-a")
    policy = ROOT / "configs/inference/policy.json"
    with pytest.raises(SystemExit, match="no frozen system"):
        cv2.check_frozen(model, policy)
    rec = cv2.freeze(model, policy, None, "dev_v1", ROOT / "data/eval_v3")
    assert rec["rules_version"] and rec["max_length"] == 512 and rec["overlap"] == 64
    assert cv2.check_frozen(model, policy)["model_sha256"] == rec["model_sha256"]
    (model / "model.safetensors").write_bytes(b"weights-b")
    with pytest.raises(SystemExit, match="model_sha256"):
        cv2.check_frozen(model, policy)


def test_predictions_fingerprint_is_stable_and_text_free():
    f = {"a": [Span(3, 9, "EMAIL")], "b": []}
    fp1 = cv2.findings_fingerprint(f, {"a": True, "b": False})
    assert fp1 == cv2.findings_fingerprint({"b": [], "a": [Span(3, 9, "EMAIL")]}, {"b": False, "a": True})
    assert fp1 != cv2.findings_fingerprint(f, {"a": True, "b": True})
