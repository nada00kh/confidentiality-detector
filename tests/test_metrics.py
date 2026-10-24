import pytest

from confidentiality_detector.decoding import decode, spans_from_tags
from confidentiality_detector.documents import Document, Span
from confidentiality_detector.labels import ID2LABEL, IGNORE_INDEX, LABEL2ID
from confidentiality_detector.metrics import (evaluate_documents, evaluate_entities, mcnemar_exact,
                                              relaxed_entity_scores, seqeval_token_metrics)


def doc(text="x" * 100, spans=(), ignore=(), negative=(), doc_id="d"):
    return Document(doc_id, text, list(spans), list(ignore), list(negative))


def test_strict_match_boundary_type_and_hard_negative():
    d = doc(
        spans=[Span(0, 5, "FIRSTNAME"), Span(10, 20, "EMAIL"), Span(30, 34, "CREDITCARDCVV")],
        negative=[Span(50, 54, "PIN")],
        ignore=[Span(70, 75, "MIDDLENAME")],
    )
    preds = {"d": [
        Span(0, 5, "FIRSTNAME"),        # TP
        Span(10, 18, "EMAIL"),          # boundary error (FP + FN)
        Span(30, 34, "PASSWORD"),       # type confusion
        Span(50, 54, "CREDITCARDCVV"),  # hard-negative FP
        Span(70, 75, "FIRSTNAME"),      # inside ignore span -> not counted
        Span(90, 95, "USERNAME"),       # spurious
    ]}
    res = evaluate_entities([d], preds)
    assert res["micro"]["tp"] == 1 and res["micro"]["fn"] == 2 and res["micro"]["fp"] == 4
    assert res["fn_breakdown"] == {"boundary": 1, "type_confusion": 1}
    assert res["fp_breakdown"] == {"boundary": 1, "type_confusion": 1, "hard_negative": 1, "spurious": 1}
    assert res["hard_negative_fp"] == {"PIN->CREDITCARDCVV": 1}
    assert res["micro"]["caught_any_type"] == 1.0
    assert res["per_class"]["EMAIL"]["overlap_recall"] == 1.0
    assert "x" not in str(res["examples"])  # reports carry shapes, not values



def test_relaxed_matching_credits_boundary_errors_but_not_type_confusion():
    d = doc(spans=[Span(0, 5, "FIRSTNAME"), Span(10, 20, "EMAIL"), Span(30, 34, "CREDITCARDCVV")],
            ignore=[Span(70, 75, "MIDDLENAME")])
    preds = {"d": [Span(0, 5, "FIRSTNAME"), Span(10, 18, "EMAIL"), Span(30, 34, "PASSWORD"),
                   Span(70, 75, "FIRSTNAME"), Span(90, 95, "USERNAME")]}
    exact = evaluate_entities([d], preds)["micro"]
    relaxed = relaxed_entity_scores([d], preds)
    # gold: FIRSTNAME exact, EMAIL boundary (found when relaxed), CVV type confusion (not found)
    assert (relaxed["gold_found"], relaxed["gold_total"]) == (2, 3)
    # predictions: the ignore-region one is not counted, as in evaluate_entities
    assert (relaxed["pred_correct"], relaxed["pred_total"]) == (2, 4)
    assert relaxed["precision"] >= exact["precision"] and relaxed["recall"] >= exact["recall"]


def test_mcnemar_exact_two_sided():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 0) == pytest.approx(2 / 32)
    assert mcnemar_exact(3, 3) == 1.0

def test_document_metrics_and_ambiguous_exclusion():
    docs = [
        doc(spans=[Span(0, 3, "SSN")], doc_id="pos_hit"),
        doc(spans=[Span(0, 3, "SSN")], doc_id="pos_miss"),
        doc(doc_id="neg_ok"),
        doc(doc_id="neg_fp"),
        doc(ignore=[Span(0, 3, "MIDDLENAME")], doc_id="ambiguous"),
    ]
    preds = {"pos_hit": [Span(0, 3, "SSN")], "neg_fp": [Span(5, 9, "IPV4")], "ambiguous": [Span(0, 3, "FIRSTNAME")]}
    res = evaluate_documents(docs, preds)
    assert res["confusion"] == {"TP_block": 1, "FN_false_allow": 1, "FP_false_block": 1, "TN_allow": 1}
    assert res["n_ambiguous_excluded"] == 1
    assert res["false_allow_rate"] == 0.5 and res["false_block_rate"] == 0.5


def test_original_metric_hides_false_positives_on_ignored_positions():
    """-100 -> O in both gold and prediction makes predictions on ignored tokens invisible."""
    pytest.importorskip("seqeval")
    o, b_pw, b_cvv = LABEL2ID["O"], LABEL2ID["B-PASSWORD"], LABEL2ID["B-CREDITCARDCVV"]
    gold = [[IGNORE_INDEX, b_pw, o, IGNORE_INDEX, IGNORE_INDEX]]  # pos 3-4: a PIN (non-target)
    pred = [[o, b_pw, o, b_cvv, o]]                                # model calls the PIN a CVV
    as_o = seqeval_token_metrics(gold, pred, ID2LABEL, ignored="as_O")
    assert as_o["precision"] == 1.0  # the CVV false positive is not visible
    d = doc(text="abcde", spans=[Span(1, 2, "PASSWORD")], negative=[Span(3, 5, "PIN")])
    char = evaluate_entities([d], {"d": [Span(1, 2, "PASSWORD"), Span(3, 4, "CREDITCARDCVV")]})
    assert char["micro"]["precision"] == 0.5


def test_lenient_decoding_starts_entity_on_orphan_I():
    spans = spans_from_tags([(0, 2), (2, 4), (5, 7), (7, 9)], ["I-EMAIL", "I-EMAIL", "O", "B-SSN"])
    assert [s.key() for s in spans] == [(0, 4, "EMAIL"), (7, 9, "SSN")]


def test_threshold_decoding_trades_recall():
    toks = [(0, 4, 0.6, LABEL2ID["B-PASSWORD"], 0.35), (5, 9, 0.95, LABEL2ID["B-SSN"], 0.03)]
    assert decode(toks) == []
    assert [s.label for s in decode(toks, threshold=0.3)] == ["PASSWORD"]


def test_three_levels_of_document_success():
    """Blocked (>= 1 caught) vs every entity caught vs exact spans."""
    from confidentiality_detector.metrics import evaluate

    d = doc(spans=[Span(0, 5, "FIRSTNAME"), Span(10, 20, "EMAIL")], doc_id="a")
    r = evaluate([d], {"a": [Span(0, 5, "FIRSTNAME")]})            # blocked, but the e-mail is missed
    assert r["document"]["block_recall"] == 1.0 and r["document"]["block_docs_fully_caught"] == 0.0
    r = evaluate([d], {"a": [Span(0, 5, "FIRSTNAME"), Span(10, 15, "EMAIL")]})  # all caught, one boundary wrong
    assert r["document"]["block_docs_fully_caught"] == 1.0 and r["entity"]["micro"]["recall"] == 0.5


def test_predictions_are_refused_on_a_different_eval_version(tmp_path):
    """Guard against scoring stored predictions on changed texts (the round-2 test_long incident)."""
    import json as _json

    from confidentiality_detector.documents import file_sha256
    from confidentiality_detector.runio import ProvenanceError, check_provenance

    eval_file = tmp_path / "set.jsonl"
    eval_file.write_text('{"doc_id": "a", "text": "hello", "spans": []}\n', encoding="utf-8")
    pred_dir = tmp_path / "run"
    pred_dir.mkdir()
    (pred_dir / "run_info.json").write_text(_json.dumps({"sets": {"set": {"eval_sha256": file_sha256(eval_file)}}}))
    check_provenance(pred_dir, "set", eval_file)  # same file: accepted
    eval_file.write_text('{"doc_id": "a", "text": "hello world", "spans": []}\n', encoding="utf-8")
    with pytest.raises(ProvenanceError, match="different|were made on"):
        check_provenance(pred_dir, "set", eval_file)
    with pytest.raises(ProvenanceError, match="no run_info"):
        check_provenance(tmp_path, "set", eval_file)
