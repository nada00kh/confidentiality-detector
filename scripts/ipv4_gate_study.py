"""Pre-registered evaluation of the IPv4 validation gate (docs/METHODOLOGY.md section 8).

  python scripts/ipv4_gate_study.py --model-dir checkpoints/r2_e3b_positive \
      --pred-dirs results/round2/predictions/r2_e3b_positive results/round2_derived/predictions/r2_e3b_positive
      ->  reports/ipv4_gate_study.json

Runs the real pipeline (ConfidentialityDetector: decoding, gate, live rules v3, reconciliation,
policy) twice per document, gate off and gate on, in `strict` and `maximum`. Token probabilities
come from stored predictions (--pred-dirs, searched in order); sets without stored predictions
(e.g. validation_long) are predicted with --model-dir after the checkpoint is verified. All
predictions must have been made with the inference windows currently in configs/inference/policy.json,
so the gate is judged on the final window configuration (run the window study first).
Prints and writes aggregates only (ids, labels, counts).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from confidentiality_detector.documents import Span, load_documents, read_jsonl  # noqa: E402
from confidentiality_detector.metrics import evaluate_documents  # noqa: E402
from confidentiality_detector.pipeline import ConfidentialityDetector  # noqa: E402
from confidentiality_detector.policy import PolicyConfig  # noqa: E402
from confidentiality_detector.runio import check_provenance, write_json  # noqa: E402
from evaluate_system import ReplayModel  # noqa: E402

SETS = ("dev_v1", "validation_long", "validation", "test", "test_format_shift", "test_long", "test_unseen_value",
        "test_novel_template", "synth_A_heldout", "synth_B_heldout", "challenge_v1_final")
BENEFIT_SETS = ("dev_v1", "validation_long", "synth_A_heldout")
MODES = ("strict", "maximum")


def windows_of(pred_dir: Path) -> dict:
    args = json.loads((pred_dir / "run_info.json").read_text(encoding="utf-8")).get("args", {})
    return {"max_length": int(args.get("max_length", 512)), "overlap": int(args.get("overlap", 64)),
            "stitching": args.get("stitching", "first")}


def token_rows(s, docs, pred_dirs, eval_dir, inference, detector_factory):
    for d in pred_dirs:
        path = d / f"{s}.jsonl"
        if path.exists():
            info = json.loads((d / "run_info.json").read_text(encoding="utf-8"))
            source = info.get("retargeted_from")
            win = windows_of(Path(source)) if source and (Path(source) / "run_info.json").exists() else windows_of(d)
            if win != inference:
                raise SystemExit(f"{d}/{s}: predictions made with windows {win}, policy.json says {inference}; "
                                 "re-predict with the final settings first")
            check_provenance(d, s, eval_dir / f"{s}.jsonl")
            rows = {r["doc_id"]: r["tokens"] for r in read_jsonl(path)}
            return {doc.text: [tuple(t) for t in rows[doc.doc_id]] for doc in docs}, f"stored ({d.name})"
    tokens = detector_factory().token_predictions([doc.text for doc in docs])
    return {doc.text: t for doc, t in zip(docs, tokens)}, "predicted locally"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred-dirs", type=Path, nargs="+", required=True)
    ap.add_argument("--model-dir", type=Path, default=None, help="for sets without stored predictions")
    ap.add_argument("--verify-pred-dir", type=Path, default=None, help="verify --model-dir against these first")
    ap.add_argument("--policy", type=Path, default=ROOT / "configs/inference/policy.json")
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval_v3")
    ap.add_argument("--sets", nargs="+", default=list(SETS))
    ap.add_argument("--device", default=None)
    args = ap.parse_args()
    from confidentiality_detector.detectors.rules import RuleDetector

    base_policy = PolicyConfig.from_json(args.policy)
    if base_policy.postprocessing["ipv4_requires_valid_address"]:
        raise SystemExit("policy.json already enables the gate; the study compares the evaluated (off) state with on")
    gated_policy = dataclasses.replace(base_policy, postprocessing={"ipv4_requires_valid_address": True})
    inference = dict(base_policy.inference)

    detector = None

    def detector_factory():
        nonlocal detector
        if detector is None:
            if args.model_dir is None:
                raise SystemExit("a set has no stored predictions; pass --model-dir")
            if args.verify_pred_dir is not None:
                from verify_checkpoint import verify

                check = verify(args.model_dir, args.verify_pred_dir, ["dev_v1"], args.eval_dir, device=args.device)
                if check["problems"]:
                    raise SystemExit("checkpoint verification failed: " + "; ".join(check["problems"]))
            from confidentiality_detector.detectors.transformer import TransformerDetector

            detector = TransformerDetector(args.model_dir, device=args.device, **inference)
        return detector

    rules = RuleDetector()
    out = {"inference": inference, "sets": {}}
    for s in args.sets:
        docs = load_documents(args.eval_dir / f"{s}.jsonl")
        texts = [d.text for d in docs]
        tokens, source = token_rows(s, docs, args.pred_dirs, args.eval_dir, inference, detector_factory)
        res = {"n_docs": len(docs), "source": source}
        for mode in MODES:
            off = ConfidentialityDetector(ReplayModel(tokens), rules, base_policy).inspect_batch(texts, mode)
            on = ConfidentialityDetector(ReplayModel(tokens), rules, gated_policy).inspect_batch(texts, mode)
            blocked_off = {d.doc_id: x.blocked for d, x in zip(docs, off)}
            blocked_on = {d.doc_id: x.blocked for d, x in zip(docs, on)}
            m_off = evaluate_documents(docs, {k: [Span(0, 1, "B")] if v else [] for k, v in blocked_off.items()})
            m_on = evaluate_documents(docs, {k: [Span(0, 1, "B")] if v else [] for k, v in blocked_on.items()})
            new_fa = [d.doc_id for d in docs if d.gold_decision() == "BLOCK" and blocked_off[d.doc_id] and not blocked_on[d.doc_id]]
            lost_ipv4, removed = 0, Counter()
            for d, a, b in zip(docs, off, on):
                kept = {(f.start, f.end, f.label) for f in b.findings}
                for f in a.findings:
                    if (f.start, f.end, f.label) not in kept:
                        removed[next((n.label for n in d.negative_spans if n.start < f.end and f.start < n.end), "none")] += 1
                for g in d.spans:
                    if g.label == "IPV4" and any(f.start < g.end and g.start < f.end for f in a.findings) \
                            and not any(f.start < g.end and g.start < f.end for f in b.findings):
                        lost_ipv4 += 1
            res[mode] = {"FA_off": m_off["confusion"]["FN_false_allow"], "FA_on": m_on["confusion"]["FN_false_allow"],
                         "FB_off": m_off["confusion"]["FP_false_block"], "FB_on": m_on["confusion"]["FP_false_block"],
                         "n_block": m_off["n_block_docs"], "n_allow": m_off["n_allow_docs"],
                         "new_false_allow_ids": new_fa, "gold_ipv4_no_longer_caught": lost_ipv4,
                         "removed_findings_by_lookalike_type": dict(removed)}
        out["sets"][s] = res
        st = res["strict"]
        print(f"{s:20} [{source}] strict FA {st['FA_off']}->{st['FA_on']} FB {st['FB_off']}->{st['FB_on']} "
              f"lost IPv4 {st['gold_ipv4_no_longer_caught']} | maximum FA {res['maximum']['FA_off']}->{res['maximum']['FA_on']} "
              f"FB {res['maximum']['FB_off']}->{res['maximum']['FB_on']}", flush=True)

    # acceptance criteria, docs/METHODOLOGY.md section 8
    sets = out["sets"].values()
    safety = all(r[m]["FA_on"] <= r[m]["FA_off"] and not r[m]["new_false_allow_ids"] for r in sets for m in MODES)
    preservation = all(r[m]["gold_ipv4_no_longer_caught"] == 0 for r in sets for m in MODES)
    benefit = any(out["sets"][s]["strict"]["FB_on"] < out["sets"][s]["strict"]["FB_off"] for s in BENEFIT_SETS if s in out["sets"])
    complete = set(SETS) <= set(out["sets"])
    out["criteria"] = {"1_no_new_false_allow": safety, "2_ipv4_detections_preserved": preservation,
                       "4_false_block_benefit": benefit, "all_sets_evaluated": complete}
    out["decision"] = "ADOPT" if safety and preservation and benefit and complete else "RETAIN (gate stays off)"
    write_json(ROOT / "reports/ipv4_gate_study.json", out)
    print(json.dumps(out["criteria"]), "->", out["decision"])
    print("Criterion 3 (integration) is covered by tests/test_postprocess.py. Nothing is changed automatically: "
          "adoption means setting postprocessing.ipv4_requires_valid_address to true in policy.json.")


if __name__ == "__main__":
    main()
