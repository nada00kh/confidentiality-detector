"""Round-1 analysis: significance of document-level differences, a validation-chosen operating
point, and challenge-set failure listing. Reads stored predictions only (no model needed).

  python scripts/analyze_round1.py  ->  reports/round1_analysis.json

Operating-point rule (fixed before looking at any test result): on VALIDATION only, choose the
smallest token threshold t in GRID whose false-block rate is at most 1 percentage point above
the argmax decoder's and whose entity F1 drops by at most 0.01. Security priority: lower t
flags more tokens (fewer false ALLOWs), and the budget caps the extra false BLOCKs.
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.detectors.hybrid import merge  # noqa: E402
from confidentiality_detector.documents import load_documents  # noqa: E402
from confidentiality_detector.metrics import evaluate, mask_value  # noqa: E402
from confidentiality_detector.runio import load_predictions  # noqa: E402

RESULTS = ROOT / "results/round1/predictions"
LOCAL = ROOT / "predictions"
GRID = [None, 0.5, 0.4, 0.3, 0.2, 0.15, 0.1, 0.05]
SETS = ("validation", "test", "test_format_shift", "test_long", "challenge_v1")


def preds(system: str, set_name: str, threshold=None) -> dict:
    model, _, hybrid = system.partition("+")
    root = RESULTS if (RESULTS / model).exists() else LOCAL
    p = load_predictions(root / model / f"{set_name}.jsonl", threshold=threshold)
    if model == "presidio":
        p = {k: [s for s in v if (s.score or 0) >= 0.3] for k, v in p.items()}
    if hybrid:
        rules = load_predictions(LOCAL / hybrid / f"{set_name}.jsonl")
        p = {k: merge(v, rules.get(k, [])) for k, v in p.items()}
    return p


def doc_outcomes(docs, p) -> dict[str, bool]:
    """doc_id -> correct decision (ambiguous docs excluded)."""
    return {d.doc_id: (bool(p.get(d.doc_id)) == d.should_block) for d in docs if d.spans or not d.ignore_spans}


def mcnemar_exact(a: dict, b: dict, ids) -> dict:
    """Exact two-sided McNemar test on paired correctness."""
    only_a = sum(a[i] and not b[i] for i in ids)
    only_b = sum(b[i] and not a[i] for i in ids)
    n = only_a + only_b
    p = min(1.0, 2 * sum(math.comb(n, k) for k in range(0, min(only_a, only_b) + 1)) / 2 ** n) if n else 1.0
    return {"only_first_correct": only_a, "only_second_correct": only_b, "p_value": p}


def bootstrap_rates(docs, p, n_boot=2000, seed=0) -> dict:
    rng = random.Random(seed)
    pos = [bool(p.get(d.doc_id)) for d in docs if d.spans]
    neg = [bool(p.get(d.doc_id)) for d in docs if not d.spans and not d.ignore_spans]
    fars, fbrs = [], []
    for _ in range(n_boot):
        fars.append(sum(not x for x in rng.choices(pos, k=len(pos))) / len(pos))
        fbrs.append(sum(rng.choices(neg, k=len(neg))) / len(neg) if neg else 0.0)
    q = lambda xs: (sorted(xs)[int(0.025 * n_boot)], sorted(xs)[int(0.975 * n_boot)])  # noqa: E731
    return {"FAR": sum(not x for x in pos) / len(pos), "FAR_ci95": q(fars),
            "FBR": (sum(neg) / len(neg)) if neg else None, "FBR_ci95": q(fbrs) if neg else None}


def summary(docs, p) -> dict:
    r = evaluate(docs, p)
    e, d = r["entity"]["micro"], r["document"]
    return {"entity_p": e["precision"], "entity_r": e["recall"], "entity_f1": e["f1"], "caught": e["caught_any_type"],
            "FAR": d["false_allow_rate"], "FBR": d["false_block_rate"], "fp_breakdown": r["entity"]["fp_breakdown"]}


def main() -> None:
    docs = {s: load_documents(ROOT / f"data/eval/{s}.jsonl") for s in SETS}
    out: dict = {}

    # 1) Paired significance of document decisions.
    systems = ["mbert_original", "e1_mbert_v2", "e2_mbert_v2_fmtA", "e2_mbert_v2_fmtA+rules_v2", "rules_v2", "presidio"]
    pairs = [("mbert_original", "e1_mbert_v2"), ("e1_mbert_v2", "e2_mbert_v2_fmtA"),
             ("e2_mbert_v2_fmtA", "e2_mbert_v2_fmtA+rules_v2"), ("mbert_original", "e2_mbert_v2_fmtA+rules_v2"),
             ("presidio", "e2_mbert_v2_fmtA+rules_v2")]
    out["significance"] = {}
    for s in ("challenge_v1", "test_format_shift", "test"):
        outcomes = {sys_: doc_outcomes(docs[s], preds(sys_, s)) for sys_ in systems}
        block_ids = [d.doc_id for d in docs[s] if d.spans]
        allow_ids = [d.doc_id for d in docs[s] if not d.spans and not d.ignore_spans]
        out["significance"][s] = {
            f"{a} vs {b}": {"BLOCK_docs (false ALLOW)": mcnemar_exact(outcomes[a], outcomes[b], block_ids),
                            **({"ALLOW_docs (false BLOCK)": mcnemar_exact(outcomes[a], outcomes[b], allow_ids)} if allow_ids else {})}
            for a, b in pairs}
        out.setdefault("bootstrap", {})[s] = {sys_: bootstrap_rates(docs[s], preds(sys_, s)) for sys_ in systems}

    # 2) Operating point chosen on validation only.
    sweep = {}
    for system in ("e2_mbert_v2_fmtA", "e2_mbert_v2_fmtA+rules_v2"):
        rows = {str(t): summary(docs["validation"], preds(system, "validation", t)) for t in GRID}
        base = rows["None"]
        eligible = [t for t in GRID if t is not None and rows[str(t)]["FBR"] <= base["FBR"] + 0.01
                    and rows[str(t)]["entity_f1"] >= base["entity_f1"] - 0.01]
        chosen = min(eligible) if eligible else None
        sweep[system] = {"validation": rows, "chosen_threshold": chosen,
                         "held_out_at_chosen": {s: summary(docs[s], preds(system, s, chosen)) for s in SETS[1:]},
                         "held_out_at_argmax": {s: summary(docs[s], preds(system, s)) for s in SETS[1:]}}
    out["operating_point"] = sweep

    # 3) Challenge failures for the candidate systems (shapes only, no values).
    fails = {}
    for system in ("e2_mbert_v2_fmtA+rules_v2", "e2_mbert_v2_fmtA"):
        p = preds(system, "challenge_v1")
        rows = []
        for d in docs["challenge_v1"]:
            if not d.spans and d.ignore_spans:
                continue
            got = p.get(d.doc_id, [])
            missed = [s for s in d.spans if not any(s.overlaps(x) for x in got)]
            false_pos = [x for x in got if not any(x.overlaps(s) for s in d.spans + d.ignore_spans)]
            if (d.should_block and not got) or (not d.should_block and got) or missed:
                rows.append({"doc_id": d.doc_id, "tags": d.meta.get("tags"),
                             "decision_error": "false_ALLOW" if d.should_block and not got else
                                               "false_BLOCK" if (not d.should_block and got) else "entity_miss_only",
                             "missed": [(s.label, mask_value(d.text[s.start:s.end])) for s in missed],
                             "false_positive": [(x.label, mask_value(d.text[x.start:x.end]),
                                                 next((n.label for n in d.negative_spans if n.overlaps(x)), None)) for x in false_pos]})
        fails[system] = rows
    out["challenge_failures"] = fails

    path = ROOT / "reports/round1_analysis.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    main()
