"""Evaluation: strict character-span entity metrics, error taxonomy, and document-level
BLOCK/ALLOW security metrics.

Entities are compared as (start, end, label) character spans on the *original document*,
so sliding windows can neither duplicate nor drop entities in the score. Predictions that
fall inside an ignore span (ambiguous annotations, e.g. MIDDLENAME) are neither rewarded nor
penalised. Out-of-scope entities (negative spans) remain scoreable, so a prediction on a
PIN, IPv6 address or IMEI counts as a false positive -- the original metric hid these.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Iterable, Mapping, Sequence

from .documents import Document, Span
from .labels import IGNORE_INDEX, TARGET_LABELS


def mask_value(value: str) -> str:
    """Shape of a value (Aa9 classes) so reports never contain the raw string."""
    value = re.sub(r"[A-Z]", "A", value)
    value = re.sub(r"[a-z]", "a", value)
    return re.sub(r"[0-9]", "9", value)


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": p, "recall": r, "f1": f, "tp": tp, "fp": fp, "fn": fn, "support": tp + fn}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _inside_any(span: Span, regions: Sequence[Span]) -> bool:
    return any(span.overlaps(r) for r in regions)


def evaluate_entities(
    docs: Sequence[Document], preds: Mapping[str, Sequence[Span]], max_examples: int = 25
) -> dict:
    tp: Counter = Counter()
    fp: Counter = Counter()
    fn: Counter = Counter()
    overlap_tp: Counter = Counter()
    caught: Counter = Counter()
    gold_errors: Counter = Counter()
    pred_errors: Counter = Counter()
    confusion: Counter = Counter()
    hard_negative_fp: Counter = Counter()
    examples: dict[str, list] = defaultdict(list)

    def example(kind: str, doc: Document, span: Span, **extra):
        if len(examples[kind]) < max_examples:
            examples[kind].append(
                {"doc_id": doc.doc_id, "start": span.start, "end": span.end, "label": span.label,
                 "shape": mask_value(doc.text[span.start:span.end]), **extra}
            )

    for doc in docs:
        gold = list(doc.spans)
        pred = [p for p in preds.get(doc.doc_id, [])]
        gold_keys = {g.key() for g in gold}
        pred_keys = {p.key() for p in pred}

        for g in gold:
            if g.key() in pred_keys:
                tp[g.label] += 1
                overlap_tp[g.label] += 1
                caught[g.label] += 1
                continue
            fn[g.label] += 1
            overlapping = [p for p in pred if p.overlaps(g)]
            if overlapping:
                caught[g.label] += 1
            same = [p for p in overlapping if p.label == g.label]
            if same:
                overlap_tp[g.label] += 1
                gold_errors["boundary"] += 1
                example("fn_boundary", doc, g, pred=[(p.start, p.end) for p in same])
            elif overlapping:
                gold_errors["type_confusion"] += 1
                for p in overlapping:
                    confusion[(g.label, p.label)] += 1
                example("fn_type_confusion", doc, g, pred_labels=[p.label for p in overlapping])
            else:
                gold_errors["missed"] += 1
                example("fn_missed", doc, g)

        for p in pred:
            if p.key() in gold_keys:
                continue
            overlapping_gold = [g for g in gold if g.overlaps(p)]
            if not overlapping_gold and _inside_any(p, doc.ignore_spans):
                continue  # ambiguous region: not counted either way
            fp[p.label] += 1
            if any(g.label == p.label for g in overlapping_gold):
                pred_errors["boundary"] += 1
            elif overlapping_gold:
                pred_errors["type_confusion"] += 1
            else:
                negatives = [n for n in doc.negative_spans if n.overlaps(p)]
                if negatives:
                    pred_errors["hard_negative"] += 1
                    for n in negatives:
                        hard_negative_fp[(n.label, p.label)] += 1
                    example("fp_hard_negative", doc, p, negative_label=negatives[0].label)
                else:
                    pred_errors["spurious"] += 1
                    example("fp_spurious", doc, p)

    labels = list(TARGET_LABELS)
    per_class = {}
    for label in labels:
        row = prf(tp[label], fp[label], fn[label])
        support = row["support"]
        row["overlap_recall"] = overlap_tp[label] / support if support else None
        row["caught_any_type"] = caught[label] / support if support else None
        per_class[label] = row
    micro = prf(sum(tp.values()), sum(fp.values()), sum(fn.values()))
    support = micro["support"]
    micro["overlap_recall"] = sum(overlap_tp.values()) / support if support else None
    micro["caught_any_type"] = sum(caught.values()) / support if support else None
    present = [l for l in labels if per_class[l]["support"]]
    macro_f1 = sum(per_class[l]["f1"] for l in present) / len(present) if present else 0.0
    return {
        "micro": micro,
        "macro_f1": macro_f1,
        "per_class": per_class,
        "fn_breakdown": dict(gold_errors),
        "fp_breakdown": dict(pred_errors),
        "type_confusion": {f"{g}->{p}": n for (g, p), n in confusion.most_common()},
        "hard_negative_fp": {f"{n}->{p}": c for (n, p), c in hard_negative_fp.most_common()},
        "examples": dict(examples),
    }


def evaluate_documents(docs: Sequence[Document], preds: Mapping[str, Sequence[Span]]) -> dict:
    """BLOCK is the positive class. AMBIGUOUS documents (explicitly marked, or whose only
    annotations are ignore spans) are excluded: we cannot say whether BLOCK is correct."""
    counts = Counter()
    ambiguous = 0
    false_allow_ids, false_block_ids = [], []
    for doc in docs:
        expected = doc.gold_decision()
        if expected == "AMBIGUOUS":
            ambiguous += 1
            continue
        gold = expected == "BLOCK"
        block = bool(preds.get(doc.doc_id))
        counts[(gold, block)] += 1
        if gold and not block:
            false_allow_ids.append(doc.doc_id)
        if block and not gold:
            false_block_ids.append(doc.doc_id)
    tp, fn = counts[(True, True)], counts[(True, False)]
    fp, tn = counts[(False, True)], counts[(False, False)]
    pos, neg = tp + fn, fp + tn
    out = prf(tp, fp, fn)
    out = {f"block_{k}": v for k, v in out.items() if k in ("precision", "recall", "f1")}
    out.update(
        {
            "confusion": {"TP_block": tp, "FN_false_allow": fn, "FP_false_block": fp, "TN_allow": tn},
            "n_docs": pos + neg,
            "n_block_docs": pos,
            "n_allow_docs": neg,
            "n_ambiguous_excluded": ambiguous,
            "false_allow_rate": fn / pos if pos else None,
            "false_allow_rate_ci95": wilson(fn, pos) if pos else None,
            "false_block_rate": fp / neg if neg else None,
            "false_block_rate_ci95": wilson(fp, neg) if neg else None,
            "accuracy": (tp + tn) / (pos + neg) if pos + neg else None,
            "false_allow_doc_ids": false_allow_ids[:50],
            "false_block_doc_ids": false_block_ids[:50],
        }
    )
    return out


def fully_caught_rate(docs: Sequence[Document], preds: Mapping[str, Sequence[Span]]) -> float | None:
    """Share of BLOCK documents in which EVERY gold target is overlapped by some prediction.
    Sits between document BLOCK recall (>= 1 caught) and strict entity recall (exact)."""
    block = [d for d in docs if d.spans]
    if not block:
        return None
    hit = sum(all(any(p.overlaps(g) for p in preds.get(d.doc_id, [])) for g in d.spans) for d in block)
    return hit / len(block)


def evaluate(docs: Sequence[Document], preds: Mapping[str, Sequence[Span]]) -> dict:
    document = evaluate_documents(docs, preds)
    document["block_docs_fully_caught"] = fully_caught_rate(docs, preds)
    return {"entity": evaluate_entities(docs, preds), "document": document}


def evaluate_by_tag(docs: Sequence[Document], preds: Mapping[str, Sequence[Span]]) -> dict:
    """Document-level metrics per challenge-set tag."""
    by_tag: dict[str, list[Document]] = defaultdict(list)
    for doc in docs:
        for tag in doc.meta.get("tags", []):
            by_tag[tag].append(doc)
    out = {}
    for tag, subset in sorted(by_tag.items()):
        d = evaluate_documents(subset, preds)
        e = evaluate_entities(subset, preds, max_examples=0)["micro"]
        out[tag] = {
            "n_docs": d["n_docs"],
            "false_allow": d["confusion"]["FN_false_allow"],
            "false_block": d["confusion"]["FP_false_block"],
            "block_docs": d["n_block_docs"],
            "allow_docs": d["n_allow_docs"],
            "entity_f1": e["f1"],
            "entity_caught_any_type": e["caught_any_type"],
        }
    return out


# --- Reproduction of the original token-level seqeval metric ---------------------------

def seqeval_token_metrics(
    label_rows: Iterable[Sequence[int]],
    pred_rows: Iterable[Sequence[int]],
    id2label: Mapping[int, str],
    ignored: str = "as_O",
) -> dict:
    """ignored="as_O" reproduces notebooks/04 compute_metrics (-100 -> O in gold *and*
    prediction); ignored="drop" removes those positions instead."""
    from seqeval.metrics import classification_report, f1_score, precision_score, recall_score
    from seqeval.scheme import IOB2

    gold_tags, pred_tags = [], []
    for labels, preds in zip(label_rows, pred_rows):
        g_row, p_row = [], []
        for label_id, pred_id in zip(labels, preds):
            if label_id == IGNORE_INDEX:
                if ignored == "drop":
                    continue
                g_row.append("O")
                p_row.append("O")
            else:
                g_row.append(id2label[int(label_id)])
                p_row.append(id2label[int(pred_id)])
        gold_tags.append(g_row)
        pred_tags.append(p_row)
    kwargs = {"scheme": IOB2, "mode": "strict"}
    return {
        "precision": precision_score(gold_tags, pred_tags, **kwargs),
        "recall": recall_score(gold_tags, pred_tags, **kwargs),
        "f1": f1_score(gold_tags, pred_tags, **kwargs),
        "report": classification_report(gold_tags, pred_tags, output_dict=True, zero_division=0, **kwargs),
    }
