"""System-level evaluation: replay stored model token probabilities through the real inference
pipeline (decoding at the mode's threshold -> live rules -> reconciliation -> security policy).

  python scripts/evaluate_system.py --results results/round2 [--runs R0 R3] [--modes strict maximum]
      ->  reports/evidence/round2_system_eval.json
  python scripts/evaluate_system.py --results results/round2 results/round2_derived predictions_v3/cpu_local \n      --rules-root predictions_v3 results/round2_derived/rules --runs R3 --modes strict --sets <...> --detail \n      --out reports/evidence/final_system_metrics_r3.json      (the final-system table)

Why: the notebook metrics are transformer-only (scripts/evaluate.py without --hybrid-with). The
product is the full pipeline, so every candidate is also scored exactly as it would run, with
three levels reported side by side for the same documents:
  model   transformer spans only (argmax), as in the notebook;
  hybrid  transformer + stored rules_v3 predictions (scripts/analysis/analyze_round2.py);
  system  ConfidentialityDetector.inspect_batch in a security mode (BLOCK/ALLOW from the policy).
`hybrid` and `system/strict` must agree; a difference would mean the stored rule predictions and
the live rules diverged. Prints aggregates only.

--results / --rules-root take several roots, searched in order, so sets predicted elsewhere
(retargeted, or predicted locally) join the same evaluation. --detail adds exact-span TP/FP/FN
and macro F1, overlap (relaxed) entity metrics, and per-class document metrics; without it the
output is unchanged.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.detectors.hybrid import merge  # noqa: E402
from confidentiality_detector.documents import Span, load_documents, read_jsonl  # noqa: E402
from confidentiality_detector.metrics import (evaluate_documents, evaluate_entities, fully_caught_rate,  # noqa: E402
                                              mcnemar_exact, relaxed_entity_scores)
from confidentiality_detector.pipeline import ConfidentialityDetector  # noqa: E402
from confidentiality_detector.policy import PolicyConfig  # noqa: E402
from confidentiality_detector.runio import check_provenance, load_predictions, write_json  # noqa: E402

RUNS = {"R0": "e2_mbert_v2_fmtA", "R1": "r2_e2_v3", "R2": "r2_e3a_hardneg", "R3": "r2_e3b_positive", "R4": "r2_e4_combined"}
SETS = ("dev_v1", "synth_A_heldout", "synth_B_heldout", "test_format_shift", "test", "test_long",
        "test_unseen_value", "test_novel_template", "challenge_v1_policy")


class ReplayModel:
    """Stands in for TransformerDetector: returns the token predictions stored by predict.py."""

    def __init__(self, tokens_by_text: dict[str, list[tuple]]):
        self.tokens_by_text = tokens_by_text

    def token_predictions(self, texts):
        return [self.tokens_by_text[t] for t in texts]


def summarise(docs, spans, blocked, detail: bool = False) -> dict:
    ent = evaluate_entities(docs, spans, max_examples=0)
    doc = evaluate_documents(docs, {k: ([Span(0, 1, "BLOCK")] if v else []) for k, v in blocked.items()})
    c = doc["confusion"]
    out = {"FA": c["FN_false_allow"], "FB": c["FP_false_block"], "n_block": doc["n_block_docs"], "n_allow": doc["n_allow_docs"],
           "n_ambiguous": doc["n_ambiguous_excluded"], "FAR": doc["false_allow_rate"], "FAR_ci95": doc["false_allow_rate_ci95"],
           "FBR": doc["false_block_rate"], "FBR_ci95": doc["false_block_rate_ci95"],
           "entity_p": ent["micro"]["precision"], "entity_r": ent["micro"]["recall"], "entity_f1": ent["micro"]["f1"],
           "caught_any_type": ent["micro"]["caught_any_type"], "fully_caught": fully_caught_rate(docs, spans),
           "per_class": {k: {m: v[m] for m in ("precision", "recall", "f1", "support")} for k, v in ent["per_class"].items()},
           "fp_breakdown": ent["fp_breakdown"], "fn_breakdown": ent["fn_breakdown"],
           "false_allow_ids": doc["false_allow_doc_ids"], "false_block_ids": doc["false_block_doc_ids"]}
    if detail:
        tp, fp, fn = ent["micro"]["tp"], ent["micro"]["fp"], ent["micro"]["fn"]
        tn = c["TN_allow"]
        allow_p = tn / (tn + c["FN_false_allow"]) if tn + c["FN_false_allow"] else None
        allow_r = tn / (tn + c["FP_false_block"]) if tn + c["FP_false_block"] else None
        out["detail"] = {
            "entity_exact": {"tp": tp, "fp": fp, "fn": fn, "precision": ent["micro"]["precision"],
                             "recall": ent["micro"]["recall"], "f1": ent["micro"]["f1"], "macro_f1": ent["macro_f1"]},
            "entity_relaxed": relaxed_entity_scores(docs, spans),
            "document": {"confusion": c, "block_precision": doc["block_precision"], "block_recall": doc["block_recall"],
                         "block_f1": doc["block_f1"], "allow_precision": allow_p, "allow_recall": allow_r,
                         "allow_f1": 2 * allow_p * allow_r / (allow_p + allow_r) if allow_p and allow_r else None,
                         "accuracy": doc["accuracy"]}}
    return out


def first_with(roots: list[Path], sub: str, set_name: str) -> Path:
    """The first root whose <sub>/ holds predictions for this set."""
    for root in roots:
        if (root / sub / f"{set_name}.jsonl").exists():
            return root / sub
    raise SystemExit(f"no {sub}/{set_name}.jsonl under {[str(r) for r in roots]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, nargs="+", required=True, help="roots holding predictions/<run>/, searched in order")
    ap.add_argument("--runs", nargs="+", default=list(RUNS))
    ap.add_argument("--sets", nargs="+", default=list(SETS))
    ap.add_argument("--modes", nargs="+", default=["strict", "maximum"])
    ap.add_argument("--policy", type=Path, default=ROOT / "configs/inference/policy.json")
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval_v3")
    ap.add_argument("--rules-root", type=Path, nargs="+", default=[ROOT / "predictions_v3"], help="searched in order")
    ap.add_argument("--rules", default="rules_v3")
    ap.add_argument("--out", type=Path, default=ROOT / "reports/evidence/round2_system_eval.json")
    ap.add_argument("--detail", action="store_true", help="add exact/relaxed entity counts and per-class document metrics")
    args = ap.parse_args()
    from confidentiality_detector.detectors.rules import RuleDetector

    policy = PolicyConfig.from_json(args.policy)
    rules_live = RuleDetector()
    out: dict = {"policy_version": policy.version, "modes": {m: vars(policy.mode(m)) for m in args.modes}, "sets": {}}
    for s in args.sets:
        eval_path = args.eval_dir / f"{s}.jsonl"
        docs = load_documents(eval_path)
        texts = [d.text for d in docs]
        rules_dir = first_with(args.rules_root, args.rules, s)
        check_provenance(rules_dir, s, eval_path)
        stored_rules = load_predictions(rules_dir / f"{s}.jsonl")
        live_rules = dict(zip((d.doc_id for d in docs), rules_live.detect_batch(texts)))
        rules_agree = sum(sorted(x.key() for x in stored_rules[d.doc_id]) == sorted(x.key() for x in live_rules[d.doc_id]) for d in docs)
        out["sets"][s] = {"n_docs": len(docs), "stored_vs_live_rules_identical_docs": rules_agree, "runs": {}}
        strict_blocked = {}
        for key in args.runs:
            pdir = first_with(args.results, f"predictions/{RUNS[key]}", s)
            check_provenance(pdir, s, eval_path)
            rows = {r["doc_id"]: r for r in read_jsonl(pdir / f"{s}.jsonl")}
            model = {k: [Span(a, b, lab, sc) for a, b, lab, sc in r["spans"]] for k, r in rows.items()}
            hybrid = {k: merge(v, stored_rules.get(k, [])) for k, v in model.items()}
            res = {"model": summarise(docs, model, {k: bool(v) for k, v in model.items()}, args.detail),
                   "hybrid": summarise(docs, hybrid, {k: bool(v) for k, v in hybrid.items()}, args.detail)}
            replay = ReplayModel({d.text: [tuple(t) for t in rows[d.doc_id]["tokens"]] for d in docs})
            system = ConfidentialityDetector(replay, rules_live, policy, model_id=RUNS[key])
            for mode in args.modes:
                decisions = system.inspect_batch(texts, mode)
                spans = {d.doc_id: [Span(f.start, f.end, f.label, f.score) for f in dec.findings] for d, dec in zip(docs, decisions)}
                res[f"system_{mode}"] = summarise(docs, spans, {d.doc_id: dec.blocked for d, dec in zip(docs, decisions)}, args.detail)
                res[f"system_{mode}"]["reasons"] = sorted({dec.reason for dec in decisions})
                if mode == "strict":
                    strict_blocked[key] = {d.doc_id: dec.blocked for d, dec in zip(docs, decisions)}
            out["sets"][s]["runs"][key] = res
        # paired comparisons of system/strict errors between every pair of runs (exact McNemar)
        if "strict" in args.modes:
            gold = {d.doc_id: d.gold_decision() for d in docs}
            paired = {}
            for i, a in enumerate(args.runs):
                for b in args.runs[i + 1:]:
                    row = {}
                    for kind, cls in (("false_allow", "BLOCK"), ("false_block", "ALLOW")):
                        ids = [k for k, g in gold.items() if g == cls]
                        err_a = {k for k in ids if strict_blocked[a][k] != (cls == "BLOCK")}
                        err_b = {k for k in ids if strict_blocked[b][k] != (cls == "BLOCK")}
                        row[kind] = {f"only_{a}": len(err_a - err_b), f"only_{b}": len(err_b - err_a),
                                     "p": mcnemar_exact(len(err_a - err_b), len(err_b - err_a))}
                    paired[f"{a} vs {b}"] = row
            out["sets"][s]["paired_system_strict"] = paired
        print(f"{s} ({len(docs)} docs; stored==live rules on {rules_agree}/{len(docs)})")
        for key, res in out["sets"][s]["runs"].items():
            line = []
            for level, r in res.items():
                far = "  n/a" if r["FAR"] is None else f"{r['FAR']:.3f}"
                fbr = "  n/a" if r["FBR"] is None else f"{r['FBR']:.3f}"
                line.append(f"{level} FA {r['FA']}/{r['n_block']} ({far}) FB {r['FB']}/{r['n_allow']} ({fbr}) F1 {r['entity_f1']:.3f}")
            print(f"  {key}: " + " | ".join(line))
    write_json(args.out, out)
    print("wrote", args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out.name)


if __name__ == "__main__":
    main()
