import codecs
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import challenge_v2 as cv2  # noqa: E402

from confidentiality_detector.challenge import CaseFileError, load_challenge, read_case_file  # noqa: E402
from confidentiality_detector.documents import Span, file_sha256  # noqa: E402

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
    overlay.write_text(json.dumps({"applies_to_sha256": file_sha256(src), "changes": {
        "code-1": {"ignore_to_negative": {"wJalrXUtnFEMIEXAMPLE": "APIKEY"}, "reason": "decision F"}}}), encoding="utf-8")
    before = load_challenge(src)
    after = apply_overlay(before, overlay, src)
    assert before[0].gold_decision() == "AMBIGUOUS" and after[0].gold_decision() == "ALLOW"
    assert [n.label for n in after[0].negative_spans] == ["APIKEY"] and not after[0].ignore_spans
    neg = after[0].negative_spans[0]
    r = evaluate(after, {"code-1": [Span(neg.start, neg.end, "PASSWORD")]})
    assert r["document"]["confusion"]["FP_false_block"] == 1 and r["entity"]["micro"]["fp"] == 1
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"applies_to_sha256": file_sha256(src), "changes": {
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
    (model / "tokenizer.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="no frozen system"):
        cv2.check_frozen(model, policy)
    rec = cv2.freeze(model, policy, None, ["dev_v1"], ROOT / "data/eval_v3", require_clean=False)
    assert rec["rules_version"] and rec["max_length"] == 512 and rec["overlap"] == 64
    assert "detectors/rules.py" in rec["code_sha256"] and "tokenizer.json" in rec["checkpoint_files_sha256"]
    assert rec["runtime"]["python"] and "commit" in rec["git"]
    assert cv2.check_frozen(model, policy)["model_sha256"] == rec["model_sha256"]
    (model / "tokenizer.json").write_text('{"changed": true}', encoding="utf-8")
    with pytest.raises(SystemExit, match="checkpoint_files_sha256"):
        cv2.check_frozen(model, policy)
    (model / "tokenizer.json").write_text("{}", encoding="utf-8")
    (model / "model.safetensors").write_bytes(b"weights-b")
    with pytest.raises(SystemExit, match="model_sha256"):
        cv2.check_frozen(model, policy)
    (model / "model.safetensors").write_bytes(b"weights-a")
    for key, value in (("code_sha256", {"detectors/rules.py": "0" * 64}), ("runtime", {"torch": "0.0"})):
        tampered = dict(rec, **{key: value})
        cv2.FROZEN.write_text(json.dumps(tampered), encoding="utf-8")
        with pytest.raises(SystemExit, match=key):
            cv2.check_frozen(model, policy)


def test_freeze_refuses_uncommitted_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(cv2, "FROZEN", tmp_path / "frozen_system.json")
    monkeypatch.setattr(cv2, "git_state", lambda: {"commit": "abc", "uncommitted_changes": True})
    model = tmp_path / "ckpt"
    model.mkdir()
    (model / "model.safetensors").write_bytes(b"w")
    with pytest.raises(SystemExit, match="commit all changes"):
        cv2.freeze(model, ROOT / "configs/inference/policy.json", None, ["dev_v1"], ROOT / "data/eval_v3")
    assert not cv2.FROZEN.exists()


def test_live_decisions_must_match_the_documented_evidence(tmp_path):
    evidence = tmp_path / "evidence.json"
    documented = {"FA": 0, "FB": 2, "false_allow_ids": [], "false_block_ids": ["a", "b"]}
    evidence.write_text(json.dumps({"sets": {"dev_v1": {"runs": {"R3": {"system_strict": documented}}}}}), encoding="utf-8")
    same = {"dev_v1/strict": dict(documented, n_docs=5, decisions_sha256="x")}
    assert cv2.compare_with_evidence(same, evidence, "R3") == []
    other = {"dev_v1/strict": dict(documented, FB=1, false_block_ids=["a"], n_docs=5, decisions_sha256="y"),
             "dev_v1/maximum": dict(documented, n_docs=5, decisions_sha256="z")}
    problems = cv2.compare_with_evidence(other, evidence, "R3")
    assert any("dev_v1/strict: FB" in p for p in problems) and any("dev_v1/maximum: not in" in p for p in problems)


def test_predictions_fingerprint_is_stable_and_text_free():
    f = {"a": [Span(3, 9, "EMAIL")], "b": []}
    fp1 = cv2.findings_fingerprint(f, {"a": True, "b": False})
    assert fp1 == cv2.findings_fingerprint({"b": [], "a": [Span(3, 9, "EMAIL")]}, {"b": False, "a": True})
    assert fp1 != cv2.findings_fingerprint(f, {"a": True, "b": True})


# --- case-file format: constructs that were lost or merged without an error ----------------
# Each test also shows what the lenient (historical) parser does, which the frozen development
# files still use; challenge_v2 is always parsed strictly.

def case_file(tmp_path, text: str, name: str = "c.txt") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


TWO_CASES = "@@ a-1 | enterprise | BLOCK\ncall [[FIRSTNAME:Mira]] today\n\n@@ a-2 | lookalike | ALLOW\norder [[!ORDERID:A-5521]] shipped\n"


def test_bom_is_a_validation_error_instead_of_a_lost_first_case(tmp_path, monkeypatch):
    monkeypatch.setattr(cv2, "STATE", tmp_path / "state")
    p = tmp_path / "c.txt"
    p.write_bytes(codecs.BOM_UTF8 + TWO_CASES.encode("utf-8"))
    assert [d.doc_id for d in load_challenge(p)] == ["a-2"]  # lenient: the first case is silently lost
    r = cv2.validate(p)
    assert not r["ok"] and r["n_cases"] == 2 and any("byte-order mark" in e for e in r["errors"])
    with pytest.raises(CaseFileError, match="byte-order mark"):
        load_challenge(p, strict=True)
    with pytest.raises(SystemExit, match="cannot seal"):
        cv2.seal(p)


def test_a_file_that_is_not_utf8_is_a_clear_validation_error(tmp_path):
    p = tmp_path / "c.txt"
    p.write_bytes(TWO_CASES.encode("utf-16"))
    r = cv2.validate(p)
    assert not r["ok"] and r["n_cases"] == 0 and any("not valid UTF-8 (it looks like UTF-16)" in e for e in r["errors"])


@pytest.mark.parametrize("header,reason", [
    ("@@ a-2 | lookalike | allow", "the decision must be upper case"),
    ("@@ a-2 | lookalike, structured | ALLOW", "spaces in the tag list"),
    ("@@ a-2 | lookalike | ALLOW | extra", "more than three"),
    ("@@ a-2 lookalike ALLOW", "missing '|' separators"),
    ("  @@ a-2 | lookalike | ALLOW", "whitespace or a byte-order mark before '@@'"),
    ("@@ a.2 | lookalike | ALLOW", "the case id may contain only"),
    ("@@ a-2 | lookalike | ALLOW please", "nothing may follow the decision"),
    ("@@ a-2 | lookalike | DENY", "the decision must be BLOCK, ALLOW or AMBIGUOUS"),
])
def test_malformed_header_is_an_error_instead_of_merging_into_the_previous_case(tmp_path, header, reason):
    p = case_file(tmp_path, TWO_CASES.replace("@@ a-2 | lookalike | ALLOW", header))
    lenient = load_challenge(p)
    assert len(lenient) == 1 and lenient[0].text.endswith("shipped")  # lenient: merged into a-1
    r = cv2.validate(p)
    assert not r["ok"] and r["n_cases"] == 1
    assert any(e.startswith("line 4: malformed case header (" + reason) and "join case a-1" in e for e in r["errors"]), r["errors"]
    assert "Mira" not in json.dumps(r) and "shipped" not in json.dumps(r)


def test_malformed_first_header_and_diff_hunks(tmp_path):
    p = case_file(tmp_path, TWO_CASES.replace("@@ a-1 | enterprise | BLOCK", "@@ a-1 | enterprise | Block"))
    r = cv2.validate(p)
    assert any(e.startswith("line 1: malformed case header") and "ignored as preamble" in e for e in r["errors"])
    # a unified-diff hunk header inside a case is case text, not a header
    diff = "@@ d-1 | structured | BLOCK\n--- a/.env\n+++ b/.env\n@@ -1,2 +1,2 @@\n-DB_PASSWORD=\n+DB_PASSWORD=[[PASSWORD:Ing3st!Now]]\n"
    q = case_file(tmp_path, diff, "diff.txt")
    docs, errors, _ = read_case_file(q, strict=True)
    assert errors == [] and "@@ -1,2 +1,2 @@" in docs[0].text


def test_comment_directly_after_a_header_is_an_error_instead_of_being_dropped(tmp_path):
    text = "@@ a-1 | structured | BLOCK\n# config for [[USERNAME:svc_ingest]]\npassword: [[PASSWORD:Ing3st!Now]]\n"
    p = case_file(tmp_path, text)
    assert [s.label for s in load_challenge(p)[0].spans] == ["PASSWORD"]  # lenient: line and annotation vanish
    r = cv2.validate(p)
    assert not r["ok"] and any(e.startswith("case a-1: line 2 starts with '# '") for e in r["errors"])
    # with a blank line after the header, a leading '#' line is case text
    q = case_file(tmp_path, text.replace("BLOCK\n", "BLOCK\n\n"), "q.txt")
    assert cv2.validate(q)["ok"]
    doc = load_challenge(q, strict=True)[0]
    assert doc.text.startswith("# config for svc_ingest") and [s.label for s in doc.spans] == ["USERNAME", "PASSWORD"]


def test_text_after_a_separator_is_an_error_instead_of_joining_the_previous_case(tmp_path):
    text = ("@@ a-1 | enterprise | ALLOW\nthe quarterly report is attached\n\n# ===== names =====\n"
            "# the next cases mention Dana Whitfield\n\n@@ a-2 | enterprise | BLOCK\ncall [[FIRSTNAME:Mira]]\n")
    p = case_file(tmp_path, text)
    assert "Dana Whitfield" in load_challenge(p)[0].text  # lenient: the comment becomes text of a-1
    r = cv2.validate(p)
    assert not r["ok"] and any(e.startswith("case a-1: separator line 4 is followed by text (line 5)") for e in r["errors"])
    assert "Dana" not in json.dumps(r)
    # a separator between cases, followed only by blank lines, is fine and dropped
    ok = case_file(tmp_path, text.replace("# the next cases mention Dana Whitfield\n", ""), "ok.txt")
    assert cv2.validate(ok)["ok"]
    assert load_challenge(ok, strict=True)[0].text == "the quarterly report is attached"
    # a separator line inside a case (a code banner) and one carrying an annotation
    banner = case_file(tmp_path, '@@ b-1 | structured | BLOCK\nimport os\n# ==========\nDB_PASSWORD = "[[PASSWORD:x7!Qa]]"\n', "b.txt")
    assert any(e.startswith("case b-1: separator line 3 is followed by text (line 4)") for e in cv2.validate(banner)["errors"])
    marked = case_file(tmp_path, "@@ m-1 | enterprise | BLOCK\ncall [[FIRSTNAME:Mira]]\n# --- contact [[EMAIL:mira@example.org]]\n", "m.txt")
    assert any("separator line 3 contains annotation markup" in e for e in cv2.validate(marked)["errors"])


def test_comment_lines_ending_a_case_are_a_warning_and_remain_case_text(tmp_path):
    text = ("@@ a-1 | structured | BLOCK\nexport PGPASSWORD=[[PASSWORD:Ing3st!Now]]\n\n# remember to unset it\n\n"
            "@@ a-2 | lookalike | ALLOW\nbuild [[!VERSION:4.12.0]]\n")
    r = cv2.validate(case_file(tmp_path, text))
    assert r["ok"] and any(w.startswith("case a-1: ends with '#' comment line(s) after a blank line (from line 4)") for w in r["warnings"])
    assert load_challenge(case_file(tmp_path, text), strict=True)[0].text.endswith("\n\n# remember to unset it")
    attached = case_file(tmp_path, text.replace("Now]]\n\n#", "Now]]\n#"), "attached.txt")
    assert not any("comment line" in w for w in cv2.validate(attached)["warnings"])


def test_preamble_markup_and_empty_cases_are_warnings(tmp_path):
    text = "notes\ncall [[FIRSTNAME:Mira]] today\n\n@@ e-1 | enterprise | ALLOW\n\n@@ e-2 | lookalike | ALLOW\nbuild [[!VERSION:4.12.0]]\n"
    r = cv2.validate(case_file(tmp_path, text))
    assert r["ok"] and r["n_cases"] == 2
    assert any(w.startswith("line 2: annotation markup before the first case header") for w in r["warnings"])
    assert "e-1: empty case text" in r["warnings"]


def test_validation_lists_every_error_at_once_without_text(tmp_path):
    text = ("@@ d-1 | enterprise | BLOCK\nmail [[EMAILADDRESS:a@b.example]]\n\n"
            "@@ d-2 | enterprise | ALLOW\nmail [[EMAIL:c@d.example]]\n\n"
            "@@ d-1 | enterprise | ALLOW\nhello there\n\n"
            "@@ d-3 | enterprise | BLOCK\npw [[PASSWORD:Xy7!kQ]] and [[PASSWORD:Zz9!\n")
    p = case_file(tmp_path, text)
    with pytest.raises(ValueError, match="unknown target label"):
        load_challenge(p)  # lenient: stops at the first problem
    r = cv2.validate(p)
    assert not r["ok"]
    for expected in ("d-1: unknown target label EMAILADDRESS", "d-2: expected ALLOW but target spans are annotated",
                     "d-3: unparsed markup remains", "duplicate case ids: d-1 (lines 1, 7)"):
        assert any(e.startswith(expected) for e in r["errors"]), (expected, r["errors"])
    blob = json.dumps(r)
    assert not any(v in blob for v in ("a@b.example", "c@d.example", "hello there", "Xy7!kQ", "Zz9!"))


def test_unicode_line_separators_stay_verbatim(tmp_path):
    p = case_file(tmp_path, "@@ u-1 | unfamiliar-format | BLOCK\nname: [[FIRSTNAME:Mira]]\x0cend\x85!\n")
    doc = load_challenge(p, strict=True)[0]
    assert doc.text == "name: Mira\x0cend\x85!" and doc.text[doc.spans[0].start:doc.spans[0].end] == "Mira"


@pytest.mark.parametrize("rel", ["data/dev/dev_v1.txt", "data/challenge/challenge_v1.txt"])
def test_frozen_development_files_pass_the_strict_checks_and_parse_identically(rel):
    docs, errors, warnings = read_case_file(ROOT / rel, strict=True)
    assert errors == [] and warnings == []
    assert [d.to_json() for d in docs] == [d.to_json() for d in load_challenge(ROOT / rel)]


def test_validate_cli_exit_codes_and_output_without_text(tmp_path, monkeypatch, capsys):
    good, bad = case_file(tmp_path, TWO_CASES, "good.txt"), case_file(tmp_path, TWO_CASES.replace("ALLOW", "allow"), "bad.txt")
    for path, code in ((good, 0), (bad, 1)):
        monkeypatch.setattr(sys, "argv", ["challenge_v2.py", "validate", str(path)])
        with pytest.raises(SystemExit) as exc:
            cv2.main()
        assert exc.value.code == code
    out = capsys.readouterr().out
    assert '"n_cases": 2' in out and "malformed case header" in out and "Mira" not in out and "A-5521" not in out


# --- look-alike false positives per TYPE ------------------------------------------------------

LOOKALIKE_CASES = """@@ l-1 | lookalike | ALLOW
parcel [[!TRACKING:1Z999AA10123456784]] and build [[!VERSION:10.4.2.1]]

@@ l-2 | lookalike | ALLOW
order [[!ORDERID:A-5521-0098]] for the team

@@ l-3 | oos-secret | BLOCK
user [[USERNAME:svc_ingest]] key [[!APIKEY:sk_test_4eC39HqLyjWDarjtT1zdp7dc]]

@@ l-4 | lookalike | AMBIGUOUS
host [[~AMBIG:10.0.0.1]] build [[!VERSION:2.1.0]]
"""


def test_lookalike_false_positives_are_reported_per_type(tmp_path):
    from confidentiality_detector.metrics import evaluate_documents, evaluate_entities

    docs = load_challenge(case_file(tmp_path, LOOKALIKE_CASES), strict=True)
    by_id = {d.doc_id: d for d in docs}

    def neg(doc_id, label):
        return next(n for n in by_id[doc_id].negative_spans if n.label == label)

    user, key = by_id["l-3"].spans[0], neg("l-3", "APIKEY")
    findings = {
        "l-1": [Span(neg("l-1", "TRACKING").start, neg("l-1", "TRACKING").end, "ACCOUNTNUMBER"),
                Span(neg("l-1", "VERSION").start, neg("l-1", "VERSION").end, "IPV4")],
        "l-2": [],
        "l-3": [Span(user.start, user.end, "USERNAME"), Span(key.start, key.end, "PASSWORD"),
                Span(user.start, key.end, "USERNAME")],  # overlaps gold too: a boundary error, not a look-alike FP
        "l-4": [Span(by_id["l-4"].ignore_spans[0].start, by_id["l-4"].ignore_spans[0].end, "IPV4"),  # inside ~: not counted
                Span(neg("l-4", "VERSION").start, neg("l-4", "VERSION").end, "IPV4")],
    }
    decisions = {"l-1": True, "l-2": False, "l-3": True, "l-4": True}
    r = cv2.score(docs, findings, decisions)
    assert r["lookalike_fp_by_type"] == {
        "APIKEY": {"annotated": 1, "hit": 1, "false_positives": 1, "predicted_as": {"PASSWORD": 1}, "allow_cases": 0, "false_block_cases": 0},
        "ORDERID": {"annotated": 1, "hit": 0, "false_positives": 0, "predicted_as": {}, "allow_cases": 1, "false_block_cases": 0},
        "TRACKING": {"annotated": 1, "hit": 1, "false_positives": 1, "predicted_as": {"ACCOUNTNUMBER": 1}, "allow_cases": 1, "false_block_cases": 1},
        "VERSION": {"annotated": 2, "hit": 2, "false_positives": 2, "predicted_as": {"IPV4": 2}, "allow_cases": 1, "false_block_cases": 1},
    }
    # consistent with, and without changing, the entity and document metrics
    entity = evaluate_entities(docs, findings, max_examples=0)
    assert r["fp_breakdown"] == entity["fp_breakdown"] == {"hard_negative": 4, "boundary": 1}
    assert sum(t["false_positives"] for t in r["lookalike_fp_by_type"].values()) == r["fp_breakdown"]["hard_negative"]
    assert r["entity_micro"] == entity["micro"] and (r["entity_micro"]["tp"], r["entity_micro"]["fp"], r["entity_micro"]["fn"]) == (1, 5, 0)
    document = evaluate_documents(docs, {k: [Span(0, 1, "BLOCK")] if v else [] for k, v in decisions.items()})
    assert r["document"]["confusion"] == document["confusion"] == {"TP_block": 1, "FN_false_allow": 0, "FP_false_block": 1, "TN_allow": 1}
    assert r["document"]["n_ambiguous_excluded"] == 1
    # one prediction across look-alikes of two types counts once under each
    both = {"l-1": [Span(neg("l-1", "TRACKING").start, neg("l-1", "VERSION").end, "ACCOUNTNUMBER")]}
    two = cv2.score(docs, both, decisions)["lookalike_fp_by_type"]
    assert two["TRACKING"]["false_positives"] == two["VERSION"]["false_positives"] == 1


# --- the evaluate command (system replaced by fakes; no model, no hidden data) ---------------

def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["challenge_v2.py", *map(str, argv)])
    cv2.main()


def test_evaluate_cli_needs_a_seal_and_a_mode_and_writes_results_and_ledger(challenge, monkeypatch, capsys, tmp_path):
    from confidentiality_detector.policy import PolicyConfig

    frozen = json.loads(cv2.FROZEN.read_text(encoding="utf-8"))
    monkeypatch.setattr(cv2, "check_frozen", lambda model_dir, policy: frozen)

    def fake_run_detector(docs, model_dir, policy_path, mode):
        by_id = {d.doc_id: d for d in docs}
        findings = {d.doc_id: [] for d in docs}
        pw, trk = by_id["c-001"].spans[0], by_id["c-002"].negative_spans[0]
        findings["c-001"] = [Span(pw.start, pw.end, "PASSWORD")]
        findings["c-002"] = [Span(trk.start, trk.end, "ACCOUNTNUMBER")]
        return findings, {k: bool(v) for k, v in findings.items()}, SimpleNamespace(policy=PolicyConfig.from_json(policy_path))

    monkeypatch.setattr(cv2, "run_detector", fake_run_detector)
    with pytest.raises(SystemExit, match="not sealed"):
        run_cli(monkeypatch, "evaluate", challenge, "--model-dir", "ckpt", "--mode", "strict")
    run_cli(monkeypatch, "seal", challenge)
    for bad in ([], ["--mode", "Strict"], ["--mode", "max"]):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "evaluate", challenge, "--model-dir", "ckpt", *bad)
        assert exc.value.code == 2  # argparse usage error, before anything runs
    assert not (cv2.STATE / "LEDGER.jsonl").exists()
    details = tmp_path / "author_only" / "details.json"
    details.parent.mkdir()
    run_cli(monkeypatch, "evaluate", challenge, "--model-dir", "ckpt", "--mode", "strict", "--case-details", details)
    run_cli(monkeypatch, "evaluate", challenge, "--model-dir", "ckpt", "--mode", "maximum")
    out = capsys.readouterr().out
    assert "mode=strict" in out and "mode=maximum" in out and "evaluated 2 times" in out

    seal = json.loads((cv2.STATE / "SEAL.json").read_text(encoding="utf-8"))
    assert seal["sha256"] == file_sha256(challenge) and seal["n_cases"] == 5
    assert set(seal["validator"]["code_sha256"]) == set(cv2.EVALUATOR_CODE)
    ledger = [json.loads(line) for line in (cv2.STATE / "LEDGER.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["mode"] for e in ledger] == ["strict", "maximum"]
    for e in ledger:
        assert e["challenge_sha256"] == seal["sha256"] and e["git_commit"] == frozen["git"]["commit"]
        assert all(e[k] == frozen[k] for k in cv2.IDENTITY_KEYS)
        assert e["evaluator"]["code_sha256"] == seal["validator"]["code_sha256"]
    assert ledger[0]["predictions_sha256"] == ledger[1]["predictions_sha256"]  # same fake system, same predictions
    for mode in ("strict", "maximum"):
        result = json.loads((cv2.STATE / f"result_ckpt_{mode}.json").read_text(encoding="utf-8"))
        doc = result["document"]
        assert (doc["n_block_docs"], doc["n_allow_docs"], doc["n_ambiguous_excluded"]) == (2, 2, 1)
        assert doc["confusion"] == {"TP_block": 1, "FN_false_allow": 1, "FP_false_block": 1, "TN_allow": 1}
        assert result["lookalike_fp_by_type"]["TRACKING"]["false_block_cases"] == 1
        assert result["ledger_entry"]["mode"] == mode and "ambiguous" in result["by_tag"]
    rows = json.loads(details.read_text(encoding="utf-8"))
    assert [r["id"] for r in rows] == ["c-001", "c-002", "c-003", "c-004", "c-005"]
    blob = "".join(p.read_text(encoding="utf-8") for p in [*cv2.STATE.iterdir(), details])
    for text in (SECRET, "4111", "1Z999AA", "tracking number", "Quarterly", "sticky note"):
        assert text not in blob
    # the evaluated file must still match the seal
    challenge.write_text(CASES.replace("monday", "tuesday"), encoding="utf-8")
    with pytest.raises(SystemExit, match="does not match the sealed"):
        run_cli(monkeypatch, "evaluate", challenge, "--model-dir", "ckpt", "--mode", "strict")


FROZEN_CHECKPOINT = ROOT / "checkpoints/r2_e3b_positive"


@pytest.mark.skipif(not (FROZEN_CHECKPOINT / "model.safetensors").exists(), reason="frozen checkpoint not available locally")
def test_evaluate_end_to_end_with_the_frozen_system_on_a_synthetic_file(challenge, monkeypatch):
    """The real path: identity check against configs/inference/frozen_system.json, then the frozen
    checkpoint, rules and policy in both modes. Synthetic cases only; state in a temporary folder."""
    pytest.importorskip("torch")
    run_cli(monkeypatch, "seal", challenge)
    for mode in ("strict", "maximum"):
        run_cli(monkeypatch, "evaluate", challenge, "--model-dir", FROZEN_CHECKPOINT, "--mode", mode)
    frozen = json.loads(cv2.FROZEN.read_text(encoding="utf-8"))
    ledger = [json.loads(line) for line in (cv2.STATE / "LEDGER.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["mode"] for e in ledger] == ["strict", "maximum"]
    assert all(e[k] == frozen[k] for e in ledger for k in cv2.IDENTITY_KEYS)
    for mode in ("strict", "maximum"):
        result = json.loads((cv2.STATE / f"result_r2_e3b_positive_{mode}.json").read_text(encoding="utf-8"))
        assert result["document"]["n_ambiguous_excluded"] == 1 and result["document"]["n_docs"] == 4
        assert "TRACKING" in result["lookalike_fp_by_type"]
