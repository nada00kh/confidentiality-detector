import json
import logging
import re
from pathlib import Path

import pytest

from confidentiality_detector.detectors.rules import RuleDetector
from confidentiality_detector.documents import Span
from confidentiality_detector.labels import LABEL2ID, TARGET_SET
from confidentiality_detector.pipeline import ConfidentialityDetector, reconcile
from confidentiality_detector.policy import BLOCK, PolicyConfig, SecurityMode

ROOT = Path(__file__).resolve().parents[1]
POLICY = PolicyConfig.from_json(ROOT / "configs/inference/policy.json")
SECRET_TEXT = "Hi Priya, my password is Zq!81kLm and my card is 4111 1111 1111 1111"


class FakeModel:
    """Token predictions over whitespace tokens: 'Priya' is a name with p=0.9, 'Zq!81kLm' a
    password with p(not O)=0.3 (only flagged at low thresholds)."""

    def token_predictions(self, texts):
        out = []
        for t in texts:
            rows = []
            for m in re.finditer(r"\S+", t):
                word = m.group().strip(",.")
                end = m.start() + len(word)
                if word == "Priya":
                    rows.append((m.start(), end, 0.1, LABEL2ID["B-FIRSTNAME"], 0.9))
                elif word == "Zq!81kLm":
                    rows.append((m.start(), end, 0.7, LABEL2ID["B-PASSWORD"], 0.3))
                else:
                    rows.append((m.start(), end, 0.99, LABEL2ID["B-EMAIL"], 0.01))
            out.append(rows)
        return out


class BrokenModel:
    def token_predictions(self, texts):
        raise RuntimeError("CUDA out of memory")


def test_policy_config_is_valid_and_restricted_to_scope():
    assert POLICY.default_mode == "strict" and POLICY.blocking_labels == TARGET_SET
    with pytest.raises(ValueError, match="outside the 13-label scope"):
        PolicyConfig(modes={"m": SecurityMode("m", None)}, default_mode="m", blocking_labels=frozenset({"APIKEY"}))
    with pytest.raises(ValueError, match="unknown security mode"):
        POLICY.mode("lenient")


def test_unknown_policy_settings_are_rejected(tmp_path):
    raw = json.loads((ROOT / "configs/inference/policy.json").read_text(encoding="utf-8"))
    raw["postprocessing"] = {"ipv4_requires_valid_address": True}  # retired setting (docs/METHODOLOGY.md section 8)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown policy settings"):
        PolicyConfig.from_json(path)


def test_block_allow_and_mode_thresholds():
    det = ConfidentialityDetector(FakeModel(), None, POLICY)
    strict = det.inspect(SECRET_TEXT)                 # argmax: name only
    assert strict.decision == BLOCK and strict.categories == ("FIRSTNAME",)
    maximum = det.inspect(SECRET_TEXT, mode="maximum")  # threshold 0.05: password too
    assert maximum.categories == ("FIRSTNAME", "PASSWORD")
    assert det.inspect("Please summarise the attached roadmap.").decision == "ALLOW"


def test_rules_add_structured_findings_with_source():
    det = ConfidentialityDetector(FakeModel(), RuleDetector(), POLICY)
    d = det.inspect(SECRET_TEXT)
    sources = {f.label: f.source for f in d.findings}
    assert sources["FIRSTNAME"] == "model" and sources["CREDITCARDNUMBER"] == "rules" and sources["PASSWORD"] == "rules"
    for f in d.findings:
        assert 0 <= f.start < f.end <= len(SECRET_TEXT)


def test_fail_closed_on_error_oversize_and_empty():
    det = ConfidentialityDetector(BrokenModel(), None, POLICY)
    d = det.inspect("anything")
    assert d.decision == BLOCK and d.reason == "INSPECTION_ERROR"
    big = ConfidentialityDetector(FakeModel(), None, POLICY).inspect("x " * (POLICY.max_chars // 2 + 1))
    assert big.decision == BLOCK and big.reason == "INPUT_TOO_LARGE"
    # decision D: the explanation says why it was blocked, and never claims something was detected
    for blocked, phrase in ((d, "could not be inspected"), (big, "too large to inspect")):
        assert phrase in blocked.explanation() and not blocked.categories and not blocked.findings
        assert "protected categories" not in blocked.explanation()
    empty = ConfidentialityDetector(FakeModel(), None, POLICY).inspect("   \n")
    assert empty.decision == "ALLOW" and empty.reason == "EMPTY_INPUT"
    with pytest.raises(TypeError):
        det.inspect(None)


def test_outputs_and_logs_never_contain_values(caplog):
    det = ConfidentialityDetector(FakeModel(), RuleDetector(), POLICY)
    with caplog.at_level(logging.INFO, logger="confidentiality_detector"):
        d = det.inspect(SECRET_TEXT, mode="maximum")
        ConfidentialityDetector(BrokenModel(), None, POLICY).inspect(SECRET_TEXT)
    blob = json.dumps(d.to_dict()) + d.explanation() + caplog.text
    for value in ("Priya", "Zq!81kLm", "4111", "1111 1111"):
        assert value not in blob
    assert "decision=BLOCK" in caplog.text


def test_reconcile_merges_without_overlap_and_prefers_rule_boundaries():
    model = [Span(0, 6, "EMAIL", 0.9), Span(10, 14, "FIRSTNAME", 0.8)]
    rules = [Span(0, 12, "EMAIL", 0.99), Span(30, 33, "CREDITCARDCVV", 0.85)]
    found = reconcile(model, rules)
    assert [(f.start, f.end, f.label, f.source) for f in found] == [(0, 12, "EMAIL", "rules"), (30, 33, "CREDITCARDCVV", "rules")]


def test_end_to_end_with_saved_checkpoint_long_document(tmp_path):
    """Real checkpoint format: save a tiny random token-classification model with the mBERT
    tokenizer, load it through the production path, and inspect a > 512-token document."""
    transformers = pytest.importorskip("transformers")
    from confidentiality_detector.labels import ID2LABEL

    try:
        tok = transformers.AutoTokenizer.from_pretrained("google-bert/bert-base-multilingual-cased")
    except Exception as exc:
        pytest.skip(f"tokenizer unavailable: {exc}")
    cfg = transformers.BertConfig(vocab_size=tok.vocab_size, hidden_size=32, num_hidden_layers=1, num_attention_heads=2,
                                  intermediate_size=64, max_position_embeddings=512, num_labels=27,
                                  id2label=ID2LABEL, label2id=LABEL2ID)
    model = transformers.BertForTokenClassification(cfg)
    model.save_pretrained(tmp_path)
    tok.save_pretrained(tmp_path)
    det = ConfidentialityDetector.load(tmp_path, ROOT / "configs/inference/policy.json", device="cpu")
    text = ("Meeting notes about the quarterly roadmap and staffing. " * 120) + "Contact jane.doe@example.org."
    widths = []  # every sequence that actually reaches the model
    det.model_detector.model.register_forward_pre_hook(lambda m, a, kw: widths.append(kw["input_ids"].shape[1]), with_kwargs=True)
    d = det.inspect(text)
    assert len(det.model_detector.tokenizer(text, verbose=False)["input_ids"]) > 1000 and widths and max(widths) <= 512
    assert (det.model_detector.max_length, det.model_detector.overlap, det.model_detector.stitching) == (512, 64, "first")
    from confidentiality_detector.detectors.transformer import TransformerDetector
    with pytest.raises(ValueError, match="exceeds the model's 512 positions"):
        TransformerDetector(tmp_path, device="cpu", max_length=1024)
    centered = TransformerDetector(tmp_path, device="cpu", stitching="centered").token_predictions([text])[0]
    first = det.model_detector.token_predictions([text])[0]
    assert [t[:2] for t in centered] == [t[:2] for t in first]  # same tokens, one prediction each
    assert d.decision == BLOCK  # the rule detector finds the e-mail at the very end, past the first window
    assert any(f.label == "EMAIL" and text[f.start:f.end] == "jane.doe@example.org" for f in d.findings)
    spans = sorted((f.start, f.end) for f in d.findings)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))  # no overlapping findings
