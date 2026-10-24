"""Span-level confidence calibration: is a predicted span's score informative about whether it
is right, and would any threshold remove the false positives?

  python scripts/analysis/calibration.py --pred-root results/round1/predictions --pred e2_mbert_v2_fmtA \
      --eval-dir data/eval --sets validation test_format_shift test_long challenge_v1

Span score = mean P(not O) over the span's tokens. A span is "correct" if it overlaps a gold
target of the same type, "wrong-type" if it overlaps a gold target of another type, and a
false positive otherwise (ignore-span overlaps are skipped, as in the metrics).
Writes reports/evidence/calibration_<pred>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.documents import load_documents  # noqa: E402
from confidentiality_detector.runio import check_provenance, load_predictions, write_json  # noqa: E402

BINS = [0.5, 0.7, 0.9, 0.97, 0.99, 1.0001]


def calibrate(docs, preds) -> dict:
    rows = []
    for d in docs:
        for p in preds.get(d.doc_id, []):
            same = any(g.overlaps(p) and g.label == p.label for g in d.spans)
            other = any(g.overlaps(p) and g.label != p.label for g in d.spans)
            if not same and not other and any(i.overlaps(p) for i in d.ignore_spans):
                continue
            rows.append((p.score or 0.0, "correct" if same else ("wrong_type" if other else "false_positive")))
    table = []
    for lo, hi in zip(BINS, BINS[1:]):
        sel = [k for s, k in rows if lo <= s < hi]
        if sel:
            table.append({"score_range": f"[{lo:.2f}, {min(hi, 1.0):.2f}]", "n": len(sel),
                          "precision_overlap": sum(k == "correct" for k in sel) / len(sel),
                          "false_positives": sum(k == "false_positive" for k in sel)})
    fps = sorted(s for s, k in rows if k == "false_positive")
    return {"n_spans": len(rows), "bins": table, "n_false_positives": len(fps),
            "false_positive_score_quartiles": [fps[int(q * (len(fps) - 1))] for q in (0.25, 0.5, 0.75)] if fps else None,
            "share_of_fps_with_score_ge_0.9": sum(s >= 0.9 for s in fps) / len(fps) if fps else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--pred-root", type=Path, default=ROOT / "predictions")
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval")
    ap.add_argument("--sets", nargs="+", required=True)
    args = ap.parse_args()
    out = {}
    for name in args.sets:
        check_provenance(args.pred_root / args.pred, name, args.eval_dir / f"{name}.jsonl")
        docs = load_documents(args.eval_dir / f"{name}.jsonl")
        out[name] = calibrate(docs, load_predictions(args.pred_root / args.pred / f"{name}.jsonl"))
        c = out[name]
        print(f"{name:20} spans {c['n_spans']:6} FPs {c['n_false_positives']:5} "
              f"FPs with score>=0.9: {c['share_of_fps_with_score_ge_0.9'] if c['share_of_fps_with_score_ge_0.9'] is None else round(c['share_of_fps_with_score_ge_0.9'], 3)}  "
              + "  ".join(f"{b['score_range']}: P={b['precision_overlap']:.2f} (n={b['n']})" for b in c["bins"]))
    write_json(ROOT / f"reports/evidence/calibration_{args.pred}.json", out)


if __name__ == "__main__":
    main()
