"""Score stored predictions against the gold evaluation sets.

  python scripts/evaluate.py --pred rules_v1
  python scripts/evaluate.py --pred mbert_v2 --threshold 0.2 --tag t0.2
  python scripts/evaluate.py --pred mbert_v2 --hybrid-with rules_v1 --tag hybrid
Writes reports/runs/<pred>[__<tag>]/metrics.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.detectors.hybrid import DEFAULT_RULE_PRIORITY, merge  # noqa: E402
from confidentiality_detector.documents import load_documents  # noqa: E402
from confidentiality_detector.metrics import evaluate, evaluate_by_tag  # noqa: E402
from confidentiality_detector.runio import EVAL_SETS, check_provenance, manifest_sets, load_predictions, write_json  # noqa: E402


def run_name(args) -> str:
    return args.pred + (f"__{args.tag}" if args.tag else "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True, help="predictions/<name> directory name")
    ap.add_argument("--tag", default="")
    ap.add_argument("--sets", nargs="+", default=None, help="default: all sets in <eval-dir>/manifest.json")
    ap.add_argument("--threshold", type=float, default=None, help="re-decode with P(not O) >= threshold")
    ap.add_argument("--min-score", type=float, default=None, help="drop spans scored below this (e.g. Presidio)")
    ap.add_argument("--hybrid-with", default=None, help="rule predictions to merge with")
    ap.add_argument("--hybrid-root", type=Path, default=None, help="where --hybrid-with predictions live (default: --pred-root)")
    ap.add_argument("--rule-priority", nargs="*", default=sorted(DEFAULT_RULE_PRIORITY))
    ap.add_argument("--rule-labels", nargs="*", default=None, help="restrict merged rule labels")
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval")
    ap.add_argument("--pred-root", type=Path, default=ROOT / "predictions")
    ap.add_argument("--out-root", type=Path, default=ROOT / "reports/runs")
    args = ap.parse_args()

    results = {"pred": args.pred, "threshold": args.threshold, "hybrid_with": args.hybrid_with,
               "rule_priority": args.rule_priority, "rule_labels": args.rule_labels, "sets": {}}
    for name in args.sets or manifest_sets(args.eval_dir):
        pred_path = args.pred_root / args.pred / f"{name}.jsonl"
        if not pred_path.exists():
            print(f"skip {name}: no predictions")
            continue
        check_provenance(pred_path.parent, name, args.eval_dir / f"{name}.jsonl")
        docs = load_documents(args.eval_dir / f"{name}.jsonl")
        preds = load_predictions(pred_path, threshold=args.threshold)
        if args.min_score is not None:
            preds = {k: [s for s in v if s.score is None or s.score >= args.min_score] for k, v in preds.items()}
        missing = {d.doc_id for d in docs} - set(preds)
        if missing:
            raise ValueError(f"{name}: {len(missing)} documents have no prediction row")
        if args.hybrid_with:
            rules_dir = (args.hybrid_root or args.pred_root) / args.hybrid_with
            check_provenance(rules_dir, name, args.eval_dir / f"{name}.jsonl")
            rules = load_predictions(rules_dir / f"{name}.jsonl")
            preds = {k: merge(v, rules.get(k, []), args.rule_priority, args.rule_labels) for k, v in preds.items()}
        res = evaluate(docs, preds)
        if name.startswith(("challenge", "dev")):
            res["by_tag"] = evaluate_by_tag(docs, preds)
        results["sets"][name] = res
        e, d = res["entity"]["micro"], res["document"]
        far = d["false_allow_rate"]
        fbr = d["false_block_rate"]
        print(f"{name:24} entP {e['precision']:.3f} entR {e['recall']:.3f} entF1 {e['f1']:.3f} "
              f"caught {e['caught_any_type'] or 0:.3f} | FAR {far if far is None else round(far, 4)} "
              f"FBR {fbr if fbr is None else round(fbr, 4)}")
    out = args.out_root / run_name(args) / "metrics.json"
    write_json(out, results)
    print("wrote", out)


if __name__ == "__main__":
    main()
