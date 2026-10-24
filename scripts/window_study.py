"""Inference-window study for long inputs (no training; CPU is enough).

  python scripts/window_study.py --model-dir checkpoints/r2_e3b_positive \
      --verify-pred-dir results/round2/predictions/r2_e3b_positive
      ->  reports/window_study_<model>.json

Background (reports/ROUND2_REPORT.md section 3): on test_long, errors that do not occur on the same
text in isolation concentrate (a) in the last tokens before a window cut, which the round-2
("first") stitching predicts with no right context, and (b) at window positions >= 128, where the
model is barely fine-tuned (99.7% of supervised training tokens sit at positions 0-127).
"centered" stitching addresses (a); shorter windows address (b), at the cost of less context.

Before any candidate is scored, the checkpoint is verified against its stored predictions
(scripts/verify_checkpoint.py on dev_v1 and test_long); the study refuses to run otherwise.
Each candidate (max_length, overlap, stitching) is scored as model + live rules, argmax (the
`strict` mode), on the selection sets validation_long, dev_v1 and validation. The adoption rule
is fixed in docs/METHODOLOGY.md section 7 BEFORE any result exists and is applied mechanically
here. test_long is scored for reporting only. Nothing changes the default: adopting a candidate
means editing the `inference` section of configs/inference/policy.json by hand afterwards.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from confidentiality_detector.detectors.hybrid import merge  # noqa: E402
from confidentiality_detector.documents import load_documents  # noqa: E402
from confidentiality_detector.metrics import evaluate  # noqa: E402
from confidentiality_detector.runio import write_json  # noqa: E402

BASELINE = (512, 64, "first")                     # the evaluated round-2 setting
CANDIDATES = [BASELINE, (512, 64, "centered"), (256, 64, "centered"), (128, 32, "centered")]
SELECTION_SETS = ("validation_long", "dev_v1", "validation")
REPORT_ONLY = ("test_long",)


def score(docs, model_preds, rule_preds) -> dict:
    preds = {d.doc_id: merge(m, r) for d, m, r in zip(docs, model_preds, rule_preds)}
    r = evaluate(docs, preds)
    c, e = r["document"]["confusion"], r["entity"]
    return {"FA": c["FN_false_allow"], "FB": c["FP_false_block"], "n_block": r["document"]["n_block_docs"],
            "n_allow": r["document"]["n_allow_docs"], "entity_p": e["micro"]["precision"], "entity_r": e["micro"]["recall"],
            "entity_f1": e["micro"]["f1"], "caught_any_type": e["micro"]["caught_any_type"],
            "boundary_fp": e["fp_breakdown"].get("boundary", 0), "boundary_fn": e["fn_breakdown"].get("boundary", 0),
            "type_confusion_fp": e["fp_breakdown"].get("type_confusion", 0), "fully_caught": r["document"]["block_docs_fully_caught"]}


def adopt(base: dict, cand: dict) -> tuple[bool, list[str]]:
    """docs/METHODOLOGY.md section 7: a candidate replaces the baseline only if it is better on long
    inputs without being worse on short ones, and detects at least as many sensitive entities."""
    vl, bl = cand["validation_long"], base["validation_long"]
    reasons = []
    long_better = (vl["FA"] <= bl["FA"] and vl["FB"] < bl["FB"]) or (vl["FA"] < bl["FA"] and vl["FB"] <= bl["FB"])
    if not long_better:
        reasons.append("validation_long: no improvement without a leakage or false-block regression")
    if (vl["caught_any_type"] or 0) < (bl["caught_any_type"] or 0):
        reasons.append("validation_long: fewer sensitive entities detected (caught, any type)")
    if cand["dev_v1"]["FA"] > base["dev_v1"]["FA"] or cand["dev_v1"]["FB"] > base["dev_v1"]["FB"] + 1:
        reasons.append("dev_v1: False ALLOW increased or False BLOCK increased by more than 1")
    if cand["validation"]["entity_f1"] < base["validation"]["entity_f1"] - 0.005:
        reasons.append("validation: entity F1 dropped by more than 0.005")
    return not reasons, reasons


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--verify-pred-dir", type=Path, required=True,
                    help="stored round-2 predictions of this checkpoint (verified before any experiment)")
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval_v3")
    ap.add_argument("--device", default=None)
    ap.add_argument("--limit-validation", type=int, default=None, help="smoke tests only: first N validation docs")
    args = ap.parse_args()
    from verify_checkpoint import verify

    from confidentiality_detector.detectors.rules import RuleDetector
    from confidentiality_detector.detectors.transformer import TransformerDetector

    check = verify(args.model_dir, args.verify_pred_dir, ["dev_v1", "test_long"], args.eval_dir, device=args.device)
    if check["problems"]:
        raise SystemExit("checkpoint verification failed; refusing to run the study: " + "; ".join(check["problems"]))
    print("checkpoint verified against", args.verify_pred_dir.name, {s: r["n_docs"] for s, r in check["sets"].items()}, flush=True)

    sets = {s: load_documents(args.eval_dir / f"{s}.jsonl") for s in SELECTION_SETS + REPORT_ONLY}
    if args.limit_validation:
        sets["validation"] = sets["validation"][:args.limit_validation]
    rules = {s: RuleDetector().detect_batch([d.text for d in docs]) for s, docs in sets.items()}
    results = {}
    for max_length, overlap, stitching in CANDIDATES:
        det = TransformerDetector(args.model_dir, device=args.device, max_length=max_length, overlap=overlap,
                                  stitching=stitching)
        key = f"{max_length}/{overlap}/{stitching}"
        results[key] = {s: score(docs, det.detect_batch([d.text for d in docs]), rules[s]) for s, docs in sets.items()}
        print(key, {s: (r["FA"], r["FB"], round(r["entity_f1"], 3), round(r["caught_any_type"] or 0, 3))
                    for s, r in results[key].items()}, flush=True)
    base_key = "/".join(map(str, BASELINE))
    base = results[base_key]
    decisions = {k: dict(zip(("adopt", "reasons"), adopt(base, v))) for k, v in results.items() if k != base_key}
    adopted = [k for k, d in decisions.items() if d["adopt"]]
    # among adoptable candidates: fewest validation_long errors (False ALLOW first), then the longer window
    chosen = min(adopted, key=lambda k: (results[k]["validation_long"]["FA"], results[k]["validation_long"]["FB"],
                                         -int(k.split("/")[0]))) if adopted else base_key
    out = {"model_dir": args.model_dir.name, "verification": check, "candidates": results, "decisions": decisions,
           "chosen": chosen, "limit_validation": args.limit_validation,
           "note": "strict mode (argmax) + rules; rule from docs/METHODOLOGY.md section 7; test_long is report-only; "
                   "adopting a candidate requires editing configs/inference/policy.json"}
    write_json(ROOT / f"reports/window_study_{args.model_dir.name}.json", out)
    for k, d in decisions.items():
        print(f"{k}: {'ADOPTABLE' if d['adopt'] else 'rejected'} {d['reasons']}")
    print("chosen:", chosen, "(baseline retained)" if chosen == base_key else "(not applied automatically)")


if __name__ == "__main__":
    main()
