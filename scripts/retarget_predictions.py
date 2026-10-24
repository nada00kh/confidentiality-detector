"""Reuse stored predictions on another version of an evaluation set, only where texts are identical.

  python scripts/retarget_predictions.py --pred e2_mbert_v2_fmtA --pred-root results/round1/predictions \
      --from-eval-dir data/eval --to-eval-dir data/eval_v3 --name e2_round1_on_v3 --out-root predictions_v3 \
      --sets test challenge_v1 challenge_v1:challenge_v1_policy

A set (optionally `source:target` to map names) is retargeted only if both files contain the
same doc ids with byte-identical texts; the gold labels may differ (that is the point). Sets
whose texts differ are refused and listed: they need fresh predictions.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.documents import file_sha256, load_documents  # noqa: E402
from confidentiality_detector.runio import check_provenance, write_json  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--pred-root", type=Path, required=True)
    ap.add_argument("--from-eval-dir", type=Path, required=True)
    ap.add_argument("--to-eval-dir", type=Path, required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--sets", nargs="+", required=True)
    args = ap.parse_args()

    src_dir, out_dir = args.pred_root / args.pred, args.out_root / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    info = {"retargeted_from": str(src_dir), "sets": {}}
    refused = []
    for item in args.sets:
        source, _, target = item.partition(":")
        target = target or source
        src_eval, dst_eval = args.from_eval_dir / f"{source}.jsonl", args.to_eval_dir / f"{target}.jsonl"
        check_provenance(src_dir, source, src_eval)  # the source predictions must belong to the source file
        a = {d.doc_id: d.text for d in load_documents(src_eval)}
        b = {d.doc_id: d.text for d in load_documents(dst_eval)}
        if a != b:
            diff = sum(a.get(k) != b.get(k) for k in set(a) | set(b))
            refused.append(f"{source}->{target}: {diff} documents differ in text or id")
            continue
        shutil.copy(src_dir / f"{source}.jsonl", out_dir / f"{target}.jsonl")
        info["sets"][target] = {"n_docs": len(b), "eval_sha256": file_sha256(dst_eval), "source_set": source,
                                "source_eval_sha256": file_sha256(src_eval)}
        print(f"retargeted {source} -> {target} ({len(b)} docs, texts identical)")
    write_json(out_dir / "run_info.json", info)
    for r in refused:
        print("REFUSED", r)


if __name__ == "__main__":
    main()
