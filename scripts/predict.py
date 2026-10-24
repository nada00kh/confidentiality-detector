"""Run a detector over evaluation sets and store predictions (no metrics here).

  python scripts/predict.py --detector rules --name rules_v1
  python scripts/predict.py --detector presidio --name presidio
  python scripts/predict.py --detector transformer --model-dir <ckpt> --name mbert_original
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.documents import file_sha256, load_documents  # noqa: E402
from confidentiality_detector.runio import EVAL_SETS, manifest_sets, environment_info, save_predictions, write_json  # noqa: E402


def build_detector(args):
    if args.detector == "rules":
        from confidentiality_detector.detectors.rules import RuleDetector
        return RuleDetector()
    if args.detector == "presidio":
        from confidentiality_detector.detectors.presidio_detector import PresidioDetector
        return PresidioDetector(score_threshold=args.presidio_threshold)
    if args.detector == "transformer":
        from confidentiality_detector.detectors.transformer import TransformerDetector
        return TransformerDetector(args.model_dir, device=args.device, batch_size=args.batch_size,
                                   max_length=args.max_length, overlap=args.overlap, stitching=args.stitching)
    raise ValueError(args.detector)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detector", required=True, choices=["rules", "presidio", "transformer"])
    ap.add_argument("--name", required=True)
    ap.add_argument("--model-dir", type=Path)
    ap.add_argument("--sets", nargs="+", default=None, help="default: all sets in <eval-dir>/manifest.json")
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval")
    ap.add_argument("--out-root", type=Path, default=ROOT / "predictions")
    ap.add_argument("--device", default=None)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--max-length", type=int, default=512)
    ap.add_argument("--overlap", type=int, default=64)
    ap.add_argument("--stitching", default="first", choices=["first", "centered"])
    ap.add_argument("--presidio-threshold", type=float, default=0.35)
    args = ap.parse_args()

    detector = build_detector(args)
    out_dir = args.out_root / args.name
    info = {"detector": args.detector, "name": args.name, "model_dir": str(args.model_dir) if args.model_dir else None,
            "args": {k: str(v) for k, v in vars(args).items()}, "environment": environment_info(), "sets": {}}
    for name in args.sets or manifest_sets(args.eval_dir):
        path = args.eval_dir / f"{name}.jsonl"
        docs = load_documents(path)
        texts = [d.text for d in docs]
        t0 = time.perf_counter()
        if args.detector == "transformer":
            tokens = detector.token_predictions(texts)
            from confidentiality_detector.decoding import decode
            spans = [decode(t) for t in tokens]
        else:
            tokens = None
            spans = detector.detect_batch(texts)
        elapsed = time.perf_counter() - t0
        save_predictions(out_dir / f"{name}.jsonl", [d.doc_id for d in docs], spans, tokens)
        info["sets"][name] = {"n_docs": len(docs), "seconds": round(elapsed, 2),
                              "ms_per_doc": round(1000 * elapsed / max(1, len(docs)), 2),
                              "eval_sha256": file_sha256(path)}
        print(f"{name}: {len(docs)} docs in {elapsed:.1f}s", flush=True)
    previous = out_dir / "run_info.json"
    if previous.exists():  # keep provenance of sets predicted by earlier calls
        old = json.loads(previous.read_text(encoding="utf-8"))
        info["sets"] = {**old.get("sets", {}), **info["sets"]}
    write_json(out_dir / "run_info.json", info)
    print(json.dumps(info["sets"], indent=1))


if __name__ == "__main__":
    main()
