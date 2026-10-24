"""Verify that a locally downloaded checkpoint is the one that produced stored predictions.

  python scripts/verify_checkpoint.py --model-dir checkpoints/r2_e3b_positive \
      --pred-dir results/round2/predictions/r2_e3b_positive \
      [--meta-dir results/round2/checkpoint_meta/r2_e3b_positive] [--sets dev_v1 test_long]
      ->  reports/evidence/checkpoint_verification_<model>.json

Read-only and CPU-friendly. It never freezes anything (that is `challenge_v2.py freeze`). Checks:
  * the folder holds weights, config and tokenizer, and loads through the production loader
    (complete weights, the 27-label mapping);
  * config.json / training_summary.json equal the copies archived with the Colab results;
  * re-predicting each set with the evaluated window settings (512 / 64 / "first") gives exactly
    the stored spans, and token probabilities within float tolerance (CPU vs GPU).
dev_v1 exercises short prompts; test_long exercises the two-window path. Output: ids, counts and
hashes only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.decoding import decode  # noqa: E402
from confidentiality_detector.documents import file_sha256, load_documents, read_jsonl  # noqa: E402
from confidentiality_detector.runio import check_provenance, write_json  # noqa: E402

EVALUATED_WINDOWS = {"max_length": 512, "overlap": 64, "stitching": "first"}
PROB_TOLERANCE = 1e-3  # CPU vs GPU float32 differences are ~1e-6; anything near this would be a different model


def verify(model_dir: Path, pred_dir: Path, sets: list[str], eval_dir: Path, meta_dir: Path | None = None,
           device: str | None = None) -> dict:
    from confidentiality_detector.detectors.transformer import TransformerDetector

    model_dir, pred_dir = Path(model_dir), Path(pred_dir)
    weights = sorted(model_dir.glob("*.safetensors"))
    report: dict = {"model_dir": model_dir.name, "pred_dir": pred_dir.name,
                    "files": sorted(p.name for p in model_dir.iterdir() if p.is_file()),
                    "weights": {p.name: {"bytes": p.stat().st_size, "sha256": file_sha256(p)} for p in weights},
                    "windows": EVALUATED_WINDOWS, "metadata": {}, "sets": {}, "problems": []}
    if not weights:
        report["problems"].append("no .safetensors weights")
    for name in ("config.json", "training_summary.json"):
        archived = meta_dir / name if meta_dir else None
        if archived and archived.exists():
            local = model_dir / name
            same = local.exists() and json.loads(local.read_text(encoding="utf-8")) == json.loads(archived.read_text(encoding="utf-8"))
            report["metadata"][name] = "identical to archived copy" if same else "DIFFERS from archived copy"
            if not same:
                report["problems"].append(f"{name} differs from {archived}")
    if report["problems"]:
        return report

    detector = TransformerDetector(model_dir, device=device, **EVALUATED_WINDOWS)  # production loader checks
    for s in sets:
        eval_path = eval_dir / f"{s}.jsonl"
        check_provenance(pred_dir, s, eval_path)
        docs = load_documents(eval_path)
        stored = {r["doc_id"]: r for r in read_jsonl(pred_dir / f"{s}.jsonl")}
        local = detector.token_predictions([d.text for d in docs])
        span_diff, max_dp = [], 0.0
        for d, tokens in zip(docs, local):
            row = stored[d.doc_id]
            if sorted(x.key() for x in decode(tokens, None)) != sorted((a, b, lab) for a, b, lab, _ in row["spans"]):
                span_diff.append(d.doc_id)
            if "tokens" in row:
                if [t[:2] for t in tokens] != [tuple(t[:2]) for t in row["tokens"]]:
                    span_diff.append(d.doc_id + " (token offsets)")
                    continue
                max_dp = max([max_dp] + [abs(a[2] - b[2]) for a, b in zip(tokens, row["tokens"])])
        report["sets"][s] = {"n_docs": len(docs), "documents_with_different_spans": len(span_diff),
                             "differing_ids": span_diff[:20], "max_abs_diff_p_not_O": round(max_dp, 8)}
        if span_diff:
            report["problems"].append(f"{s}: {len(span_diff)} documents differ from the stored predictions")
        if max_dp > PROB_TOLERANCE:
            report["problems"].append(f"{s}: token probabilities differ by up to {max_dp:.2e}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--pred-dir", type=Path, required=True)
    ap.add_argument("--meta-dir", type=Path, default=None, help="archived checkpoint_meta/<run> from the Colab results")
    ap.add_argument("--sets", nargs="+", default=["dev_v1", "test_long"])
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval_v3")
    ap.add_argument("--device", default=None)
    args = ap.parse_args()
    if not args.model_dir.is_dir():
        raise SystemExit(f"checkpoint folder not found: {args.model_dir}")
    report = verify(args.model_dir, args.pred_dir, args.sets, args.eval_dir, args.meta_dir, args.device)
    report["verified"] = not report["problems"]
    write_json(ROOT / f"reports/evidence/checkpoint_verification_{args.model_dir.name}.json", report)
    for name, w in report["weights"].items():
        print(f"{name}: {w['bytes']:,} bytes, sha256 {w['sha256'][:16]}...")
    for name, status in report["metadata"].items():
        print(f"{name}: {status}")
    for s, r in report["sets"].items():
        print(f"{s}: {r['n_docs']} docs, {r['documents_with_different_spans']} with different spans, "
              f"max |dP(not O)| {r['max_abs_diff_p_not_O']}")
    print("VERIFIED" if report["verified"] else "NOT VERIFIED: " + "; ".join(report["problems"]))
    sys.exit(0 if report["verified"] else 1)


if __name__ == "__main__":
    main()
