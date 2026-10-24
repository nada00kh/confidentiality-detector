"""Security-mode evidence: False ALLOW vs False BLOCK across operating points, on a selection set.

  python scripts/analysis/operating_points.py --pred r2_e3a_hardneg --pred-root results/round2/predictions \
      --rules rules_v3 --rules-root predictions_v3 --eval-dir data/eval_v3 --set dev_v1

Two knobs, both applied to the model only (rule findings are kept as they are):
  * token threshold t: a token counts as sensitive when P(not O) >= t (None = argmax); lower t
    raises recall;
  * minimum span score s: model spans whose mean P(not O) is below s are dropped; higher s
    raises precision.
The table is evidence for a product decision; it does not choose an operating point.
Use a development set (dev_v1), never the final benchmark.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.detectors.hybrid import merge  # noqa: E402
from confidentiality_detector.documents import load_documents  # noqa: E402
from confidentiality_detector.metrics import evaluate  # noqa: E402
from confidentiality_detector.runio import check_provenance, load_predictions, write_json  # noqa: E402

THRESHOLDS = [None, 0.5, 0.3, 0.2, 0.1, 0.05]
MIN_SCORES = [0.0, 0.9, 0.97, 0.99]


def sweep(docs, model_path: Path, rules: dict | None) -> list[dict]:
    rows = []
    for t in THRESHOLDS:
        base = load_predictions(model_path, threshold=t, redecode=True)
        for s in MIN_SCORES:
            model = {k: [x for x in v if (x.score or 0.0) >= s] for k, v in base.items()}
            preds = {k: merge(v, rules.get(k, [])) for k, v in model.items()} if rules is not None else model
            r = evaluate(docs, preds)
            d, e = r["document"], r["entity"]["micro"]
            rows.append({"token_threshold": t, "min_span_score": s,
                         "false_allow": d["confusion"]["FN_false_allow"], "false_block": d["confusion"]["FP_false_block"],
                         "FAR": d["false_allow_rate"], "FAR_ci95": d["false_allow_rate_ci95"],
                         "FBR": d["false_block_rate"], "FBR_ci95": d["false_block_rate_ci95"],
                         "entity_f1": e["f1"], "caught_any_type": e["caught_any_type"]})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--pred-root", type=Path, required=True)
    ap.add_argument("--rules", default=None)
    ap.add_argument("--rules-root", type=Path, default=ROOT / "predictions_v3")
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval_v3")
    ap.add_argument("--set", default="dev_v1")
    args = ap.parse_args()
    if args.set.startswith("challenge_v2"):
        raise SystemExit("operating points must be chosen on a development set, not on the final benchmark")
    eval_path = args.eval_dir / f"{args.set}.jsonl"
    docs = load_documents(eval_path)
    check_provenance(args.pred_root / args.pred, args.set, eval_path)
    if args.rules:
        check_provenance(args.rules_root / args.rules, args.set, eval_path)
    rules = load_predictions(args.rules_root / args.rules / f"{args.set}.jsonl") if args.rules else None
    rows = sweep(docs, args.pred_root / args.pred / f"{args.set}.jsonl", rules)
    print(f"{args.pred}{' + ' + args.rules if args.rules else ''} on {args.set}")
    print("threshold  min_score  false_allow  FAR     false_block  FBR     entity_F1")
    for r in rows:
        print(f"{str(r['token_threshold']):9}  {r['min_span_score']:<9}  {r['false_allow']:<11}  {r['FAR']:.3f}   "
              f"{r['false_block']:<11}  {r['FBR']:.3f}   {r['entity_f1']:.3f}")
    write_json(ROOT / f"reports/evidence/operating_points_{args.pred}{'__' + args.rules if args.rules else ''}_{args.set}.json", rows)


if __name__ == "__main__":
    main()
