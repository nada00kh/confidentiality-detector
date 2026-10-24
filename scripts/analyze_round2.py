"""Apply the pre-registered round-2 selection rule (docs/METHODOLOGY.md section 6) mechanically.

  python scripts/analyze_round2.py --results results/round2     ->  reports/round2_selection.json

Every run is scored as model + rules_v3 (argmax) on the v3 suite; each candidate is compared
with its parent on the same documents (exact McNemar on per-document correctness).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.detectors.hybrid import merge  # noqa: E402
from confidentiality_detector.documents import load_documents  # noqa: E402
from confidentiality_detector.metrics import evaluate  # noqa: E402
from confidentiality_detector.runio import check_provenance, load_predictions, write_json  # noqa: E402

RUNS = {"R0": "e2_mbert_v2_fmtA", "R1": "r2_e2_v3", "R2": "r2_e3a_hardneg", "R3": "r2_e3b_positive", "R4": "r2_e4_combined"}
PARENT = {"R1": "R0", "R2": "R1", "R3": "R1", "R4": "R1"}
SETS = ("dev_v1", "synth_A_heldout", "synth_B_heldout", "test_format_shift", "test", "challenge_v1_policy")


def mcnemar(a: dict, b: dict, ids) -> dict:
    only_a = sum(a[i] and not b[i] for i in ids)
    only_b = sum(b[i] and not a[i] for i in ids)
    n = only_a + only_b
    p = min(1.0, 2 * sum(math.comb(n, k) for k in range(min(only_a, only_b) + 1)) / 2 ** n) if n else 1.0
    return {"parent_only_correct": only_a, "candidate_only_correct": only_b, "p": p}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True, help="extracted round2_results.zip")
    ap.add_argument("--rules", default="rules_v3")
    ap.add_argument("--rules-root", type=Path, default=ROOT / "predictions_v3")
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval_v3")
    ap.add_argument("--sets", nargs="+", default=list(SETS))
    args = ap.parse_args()

    docs = {s: load_documents(args.eval_dir / f"{s}.jsonl") for s in args.sets}
    metrics, correct = {}, {}
    for key, run in RUNS.items():
        metrics[key], correct[key] = {}, {}
        for s in args.sets:
            path = args.results / "predictions" / run / f"{s}.jsonl"
            if not path.exists():
                continue
            check_provenance(path.parent, s, args.eval_dir / f"{s}.jsonl")
            check_provenance(args.rules_root / args.rules, s, args.eval_dir / f"{s}.jsonl")
            rules = load_predictions(args.rules_root / args.rules / f"{s}.jsonl")
            preds = {k: merge(v, rules.get(k, [])) for k, v in load_predictions(path).items()}
            r = evaluate(docs[s], preds)
            d, e = r["document"], r["entity"]["micro"]
            metrics[key][s] = {"FA": d["confusion"]["FN_false_allow"], "FB": d["confusion"]["FP_false_block"],
                               "FAR": d["false_allow_rate"], "FBR": d["false_block_rate"], "entity_f1": e["f1"],
                               "fully_caught": d["block_docs_fully_caught"], "caught": e["caught_any_type"]}
            correct[key][s] = {x.doc_id: bool(preds.get(x.doc_id)) == (x.gold_decision() == "BLOCK")
                               for x in docs[s] if x.gold_decision() != "AMBIGUOUS"}

    def block_ids(s):
        return [x.doc_id for x in docs[s] if x.gold_decision() == "BLOCK"]

    def allow_ids(s):
        return [x.doc_id for x in docs[s] if x.gold_decision() == "ALLOW"]

    decisions = {}
    for key, parent in PARENT.items():
        c, p = metrics.get(key, {}), metrics.get(parent, {})
        if "dev_v1" not in c or "dev_v1" not in p:
            continue
        leak_tests = {s: mcnemar(correct[parent][s], correct[key][s], block_ids(s))
                      for s in ("synth_B_heldout", "test_format_shift") if s in c}
        crit1 = (c["dev_v1"]["FA"] <= p["dev_v1"]["FA"] + 1 and all(
            (c[s]["FAR"] or 0) <= (p[s]["FAR"] or 0) + 0.005 and not (
                leak_tests[s]["p"] < 0.05 and leak_tests[s]["parent_only_correct"] > leak_tests[s]["candidate_only_correct"])
            for s in leak_tests))
        if key == "R1":
            crit2 = True  # label-correctness fix: no benefit required
        elif key == "R3":
            crit2 = c["dev_v1"]["FA"] < p["dev_v1"]["FA"] or (c.get("synth_B_heldout", {}).get("FAR", 1) < p.get("synth_B_heldout", {}).get("FAR", 1))
        else:
            crit2 = c["dev_v1"]["FB"] < p["dev_v1"]["FB"] or (c.get("synth_A_heldout", {}).get("FBR", 1) < p.get("synth_A_heldout", {}).get("FBR", 1))
        t, tp = c.get("test", {}), p.get("test", {})
        crit3 = bool(t and tp) and t["entity_f1"] >= tp["entity_f1"] - 0.005 and abs((t["FAR"] or 0) - (tp["FAR"] or 0)) <= 0.005 \
            and abs((t["FBR"] or 0) - (tp["FBR"] or 0)) <= 0.005
        decisions[key] = {"vs": parent, "leakage_non_inferior": crit1, "benefit": crit2, "no_in_distribution_regression": crit3,
                          "passes": crit1 and crit2 and crit3, "leak_tests": leak_tests,
                          "dev_false_block_test": mcnemar(correct[parent]["dev_v1"], correct[key]["dev_v1"], allow_ids("dev_v1")),
                          "dev_false_allow_test": mcnemar(correct[parent]["dev_v1"], correct[key]["dev_v1"], block_ids("dev_v1"))}

    # adoption (docs/METHODOLOGY.md section 6.4)
    chain = "R1" if decisions.get("R1", {}).get("passes") else "R0"
    singles = [k for k in ("R2", "R3") if decisions.get(k, {}).get("passes")]
    if decisions.get("R2", {}).get("leakage_non_inferior") and decisions.get("R3", {}).get("leakage_non_inferior") \
            and decisions.get("R4", {}).get("passes"):
        selected = "R4"
    elif singles:
        selected = min(singles, key=lambda k: (metrics[k]["dev_v1"]["FA"], metrics[k]["dev_v1"]["FB"]))
    else:
        selected = chain
    out = {"metrics": metrics, "decisions": decisions, "selected": selected, "selected_run": RUNS[selected],
           "note": "model + rules_v3, argmax; criteria from docs/METHODOLOGY.md section 6"}
    write_json(ROOT / "reports/round2_selection.json", out)
    print(f"{'run':4} {'set':20} {'FA':>4} {'FB':>4} {'FAR':>7} {'FBR':>7} {'entF1':>7} {'fully':>7}")
    for key in RUNS:
        for s, m in metrics.get(key, {}).items():
            print(f"{key:4} {s:20} {m['FA']:>4} {m['FB']:>4} {m['FAR'] or 0:7.3f} {m['FBR'] if m['FBR'] is not None else float('nan'):7.3f} "
                  f"{m['entity_f1']:7.3f} {m['fully_caught'] if m['fully_caught'] is not None else float('nan'):7.3f}")
    for key, d in decisions.items():
        print(f"{key} vs {d['vs']}: leak-non-inferior={d['leakage_non_inferior']} benefit={d['benefit']} "
              f"no-regression={d['no_in_distribution_regression']} -> {'PASS' if d['passes'] else 'fail'}")
    print("selected:", selected, RUNS[selected])


if __name__ == "__main__":
    main()
