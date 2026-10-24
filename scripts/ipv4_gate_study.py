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
from confidentiality_detector.metrics import evaluate, evaluate_documents  # noqa: E402
from confidentiality_detector.pipeline import ConfidentialityDetector  # noqa: E402
from confidentiality_detector.policy import PolicyConfig  # noqa: E402
from confidentiality_detector.runio import check_provenance, write_json  # noqa: E402
from evaluate_system import ReplayModel  # noqa: E402

SETS = ("dev_v1", "validation_long", "validation", "test", "test_format_shift", "test_long", "test_unseen_value",
        "test_novel_template", "synth_A_heldout", "synth_B_heldout", "challenge_v1_final")
BENEFIT_SETS = ("dev_v1", "validation_long", "synth_A_heldout")
MODES = ("strict", "maximum")
# Address formats absent from every evaluation set (fictional RFC 5737 addresses). Reported, not a
# criterion: shows where the gate would discard a model detection that the rules do not repeat.
FORMAT_PROBE = (
    ("canonical", "The staging server is at 192.0.2.17, please ssh in and restart nginx."),
    ("with port", "Our VPN gateway 198.51.100.4:443 keeps timing out since this morning."),
    ("CIDR", "Please allow 192.0.2.17/24 through the office firewall."),
    ("trailing period", "The failed logins all came from 198.51.100.23."),
    ("prefixed word", "Set host=203.0.113.9 in the config and redeploy."),
    ("defanged [.]", "Block traffic from 203[.]0[.]113[.]9 in the firewall, it is scanning us."),
    ("defanged (dot)", "The attacker used 203(dot)0(dot)113(dot)9 according to the SOC ticket."),
    ("leading zeros", "Server address: 192.000.002.017, user is the usual admin account."),
    ("spaced", "Connect to 192 . 0 . 2 . 17 from the jump host before the migration."),
    ("commas", "Our office server ip is 192,0,2,17 if you need to whitelist it."),
    ("mistyped octet > 255", "The host 203.0.113.256 is unreachable from the build agents."),
    ("three octets", "Use 198.51.100 as the subnet prefix for the new VLAN."),
    ("hostname-encoded", "The box is srv-192-0-2-17.internal in the old naming scheme."),
    ("version string", "Release v2.14.3.1 fixed the memory leak in the parser."),
    ("bare version quad", "Please upgrade the agent to 10.4.2.1 before Friday."),
)


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
            # entity level (reported, not an adoption criterion)
            ent_off, ent_on = (evaluate(docs, {d.doc_id: [Span(f.start, f.end, f.label) for f in x.findings]
                                               for d, x in zip(docs, xs)})["entity"]["micro"] for xs in (off, on))
            lost_ipv4, removed, removed_gold = 0, Counter(), Counter()
            for d, a, b in zip(docs, off, on):
                kept = {(f.start, f.end, f.label) for f in b.findings}
                for f in a.findings:
                    if (f.start, f.end, f.label) not in kept:
                        removed[next((n.label for n in d.negative_spans if n.start < f.end and f.start < n.end), "none")] += 1
                        removed_gold[next((g.label for g in d.spans if g.start < f.end and f.start < g.end), "none")] += 1
                for g in d.spans:
                    if g.label == "IPV4" and any(f.start < g.end and g.start < f.end for f in a.findings) \
                            and not any(f.start < g.end and g.start < f.end for f in b.findings):
                        lost_ipv4 += 1
            res[mode] = {"FA_off": m_off["confusion"]["FN_false_allow"], "FA_on": m_on["confusion"]["FN_false_allow"],
                         "FB_off": m_off["confusion"]["FP_false_block"], "FB_on": m_on["confusion"]["FP_false_block"],
                         "n_block": m_off["n_block_docs"], "n_allow": m_off["n_allow_docs"],
                         "new_false_allow_ids": new_fa, "gold_ipv4_no_longer_caught": lost_ipv4,
                         "removed_findings_by_lookalike_type": dict(removed),
                         "removed_findings_by_overlapping_gold_label": dict(removed_gold),
                         "entity_off": {k: ent_off[k] for k in ("precision", "recall", "f1", "caught_any_type")},
                         "entity_on": {k: ent_on[k] for k in ("precision", "recall", "f1", "caught_any_type")}}
        out["sets"][s] = res
        st = res["strict"]
        print(f"{s:20} [{source}] strict FA {st['FA_off']}->{st['FA_on']} FB {st['FB_off']}->{st['FB_on']} "
              f"lost IPv4 {st['gold_ipv4_no_longer_caught']} | maximum FA {res['maximum']['FA_off']}->{res['maximum']['FA_on']} "
              f"FB {res['maximum']['FB_off']}->{res['maximum']['FB_on']}", flush=True)

    if args.model_dir is not None:
        texts = [t for _, t in FORMAT_PROBE]
        out["format_probe"] = {}
        for mode in MODES:
            off = ConfidentialityDetector(detector_factory(), rules, base_policy).inspect_batch(texts, mode)
            on = ConfidentialityDetector(detector_factory(), rules, gated_policy).inspect_batch(texts, mode)
            out["format_probe"][mode] = [
                {"case": name, "off": a.decision, "on": b.decision,
                 "findings_off": sorted(f"{f.label}/{f.source}" for f in a.findings),
                 "findings_on": sorted(f"{f.label}/{f.source}" for f in b.findings)}
                for (name, _), a, b in zip(FORMAT_PROBE, off, on)]
            changed = [p["case"] for p in out["format_probe"][mode] if p["off"] != p["on"]]
            print(f"format probe ({mode}): gate turns BLOCK into ALLOW for {changed}", flush=True)

    # acceptance criteria, docs/METHODOLOGY.md section 8 (necessary conditions: the gate is switched on ONLY IF they hold)
    sets = out["sets"].values()
    safety = all(r[m]["FA_on"] <= r[m]["FA_off"] and not r[m]["new_false_allow_ids"] for r in sets for m in MODES)
    preservation = all(r[m]["gold_ipv4_no_longer_caught"] == 0 for r in sets for m in MODES)
    benefit = any(out["sets"][s]["strict"]["FB_on"] < out["sets"][s]["strict"]["FB_off"] for s in BENEFIT_SETS if s in out["sets"])
    complete = set(SETS) <= set(out["sets"])
    out["criteria"] = {"1_no_new_false_allow": safety, "2_ipv4_detections_preserved": preservation,
                       "4_false_block_benefit": benefit, "all_sets_evaluated": complete}
    out["decision"] = "ELIGIBLE (criteria met)" if safety and preservation and benefit and complete else "RETAIN (gate stays off)"
    write_json(ROOT / "reports/ipv4_gate_study.json", out)
    print(json.dumps(out["criteria"]), "->", out["decision"])
    print("Criterion 3 (integration) is covered by tests/test_postprocess.py. Nothing is changed automatically: "
          "adoption means setting postprocessing.ipv4_requires_valid_address to true in policy.json; "
          "the decision and its reasons are recorded in docs/METHODOLOGY.md section 8.")


if __name__ == "__main__":
    main()
