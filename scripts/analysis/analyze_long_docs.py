"""Explain test_long results: are long-document errors caused by length/windowing, or are they
the same errors the model makes on the component documents in isolation?

  python scripts/analysis/analyze_long_docs.py --results results/round2   ->  reports/evidence/round2_long_docs.json

test_long documents are concatenations of test documents (meta["parents"]): a BLOCK document
hides one PII-bearing test document among 8-14 target-free ones; an ALLOW document contains
only target-free test documents (which carry out-of-scope PII such as dates, URLs, crypto
addresses). Every component also exists on its own in test.jsonl, with byte-identical text,
so each long-document error can be compared with the prediction on the same text in isolation.

For every prediction error the script records the component it falls in, the inference window
that owns it (512 tokens, 64 overlap, as in predict.py), its distance in tokens from the nearest
window boundary, and whether the same error occurs on the standalone component. Output contains
ids, labels and positions only, never document text.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.alignment import encode_text, inference_windows  # noqa: E402
from confidentiality_detector.detectors.hybrid import merge  # noqa: E402
from confidentiality_detector.documents import Span, load_documents  # noqa: E402
from confidentiality_detector.metrics import evaluate  # noqa: E402
from confidentiality_detector.runio import check_provenance, load_predictions, write_json  # noqa: E402

RUNS = {"R0": "e2_mbert_v2_fmtA", "R1": "r2_e2_v3", "R2": "r2_e3a_hardneg", "R3": "r2_e3b_positive", "R4": "r2_e4_combined"}
SEP = "\n\n"


def components(doc, parents):
    """(parent id, start, end) of each component inside the long document."""
    out, offset = [], 0
    for p in parents:
        out.append((p.doc_id, offset, offset + len(p.text)))
        offset += len(p.text) + len(SEP)
    return out


def window_geometry(tokenizer, text):
    enc = encode_text(tokenizer, text)
    windows = inference_windows(len(enc.input_ids), 512, 64)
    # character offset where each window after the first starts owning tokens
    boundaries = [enc.offsets[w.own_start][0] for w in windows[1:]]
    return enc, windows, boundaries


def locate(span, comps, enc, windows):
    comp = next(((cid, s) for cid, s, e in comps if s <= span.start < e), (None, None))
    tok = next((i for i, (s, e) in enumerate(enc.offsets) if e > span.start), len(enc.offsets) - 1)
    win = next(k for k, w in enumerate(windows) if w.own_start <= tok < w.end)
    w = windows[win]
    # distance to the closest edge of the window's visible context (left context start / right end)
    dist = min(tok - w.context_start, w.end - 1 - tok)
    return {"component": comp[0], "component_offset": comp[1], "token": tok, "n_tokens": len(enc.offsets),
            "window": win, "tokens_from_window_edge": dist,
            "crosses_component_boundary": any(s < span.end and span.start < e and not (s <= span.start and span.end <= e)
                                              for _, s, e in comps)}


def same_in_isolation(span, comp_offset, standalone_preds, kind):
    shifted = [(p.start + comp_offset, p.end + comp_offset, p.label) for p in standalone_preds]
    if kind == "fp":  # same false positive (exact span) predicted on the standalone document?
        return (span.start, span.end, span.label) in shifted
    return any(s < span.end and span.start < e for s, e, _ in shifted)  # missed entity: caught standalone?


def analyse(docs, parents_of, preds, standalone, enc_cache):
    rows = []
    for d in docs:
        comps = components(d, parents_of[d.doc_id])
        enc, windows, _ = enc_cache[d.doc_id]
        p = preds[d.doc_id]
        relevant = d.spans + d.ignore_spans
        fps = [s for s in p if not any(s.overlaps(g) for g in relevant)]
        fns = [g for g in d.spans if not any(s.overlaps(g) for s in p)]
        errs = []
        for kind, items in (("fp", fps), ("fn", fns)):
            for s in items:
                loc = locate(s, comps, enc, windows)
                loc.update(kind=kind, label=s.label,
                           hit_negative_type=next((n.label for n in d.negative_spans if n.overlaps(s)), None) if kind == "fp" else None,
                           same_error_in_isolation=(same_in_isolation(s, loc["component_offset"], standalone[loc["component"]], kind)
                                                    if kind == "fp" else not same_in_isolation(s, loc["component_offset"], standalone[loc["component"]], kind)))
                errs.append(loc)
        rows.append({"doc_id": d.doc_id, "gold": d.gold_decision(), "pred": "BLOCK" if p else "ALLOW",
                     "n_tokens": len(enc.offsets), "n_windows": len(windows), "n_components": len(comps),
                     "n_gold": len(d.spans), "errors": errs})
    return rows


def summarise(rows):
    errs = [e for r in rows for e in r["errors"]]
    fb = [r for r in rows if r["gold"] == "ALLOW" and r["pred"] == "BLOCK"]
    fa = [r for r in rows if r["gold"] == "BLOCK" and r["pred"] == "ALLOW"]
    near_edge = [e for e in errs if e["tokens_from_window_edge"] < 32]
    return {
        "false_block_docs": [r["doc_id"] for r in fb], "false_allow_docs": [r["doc_id"] for r in fa],
        "n_fp": sum(e["kind"] == "fp" for e in errs), "n_fn": sum(e["kind"] == "fn" for e in errs),
        "fp_same_as_isolation": sum(e["kind"] == "fp" and e["same_error_in_isolation"] for e in errs),
        "fn_same_as_isolation": sum(e["kind"] == "fn" and e["same_error_in_isolation"] for e in errs),
        "errors_in_window_2_plus": sum(e["window"] > 0 for e in errs),
        "errors_within_32_tokens_of_window_edge": len(near_edge),
        "errors_crossing_component_boundary": sum(e["crosses_component_boundary"] for e in errs),
        "fp_labels": dict(Counter(e["label"] for e in errs if e["kind"] == "fp")),
        "fp_hit_negative_types": dict(Counter(e["hit_negative_type"] or "none" for e in errs if e["kind"] == "fp")),
        "fn_labels": dict(Counter(e["label"] for e in errs if e["kind"] == "fn")),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval_v3")
    ap.add_argument("--rules-root", type=Path, default=ROOT / "predictions_v3")
    ap.add_argument("--rules", default="rules_v3")
    ap.add_argument("--tokenizer", default="google-bert/bert-base-multilingual-cased")
    args = ap.parse_args()
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer)
    long_docs = load_documents(args.eval_dir / "test_long.jsonl")
    test = {d.doc_id: d for d in load_documents(args.eval_dir / "test.jsonl")}
    parents_of = {d.doc_id: [test[p] for p in d.meta["parents"]] for d in long_docs}
    for d in long_docs:  # the components must be byte-identical to their standalone documents
        if SEP.join(p.text for p in parents_of[d.doc_id]) != d.text:
            raise SystemExit(f"{d.doc_id}: text is not the concatenation of its parents")
    enc_cache = {d.doc_id: window_geometry(tokenizer, d.text) for d in long_docs}

    rules = {}
    for s in ("test_long", "test"):
        check_provenance(args.rules_root / args.rules, s, args.eval_dir / f"{s}.jsonl")
        rules[s] = load_predictions(args.rules_root / args.rules / f"{s}.jsonl")

    out = {"n_docs": len(long_docs), "decisions": dict(Counter(d.gold_decision() for d in long_docs)),
           "tokens": {"min": min(len(e[0].offsets) for e in enc_cache.values()), "max": max(len(e[0].offsets) for e in enc_cache.values())},
           "windows_per_doc": dict(Counter(len(e[1]) for e in enc_cache.values())),
           "components_per_doc": dict(Counter(len(v) for v in parents_of.values())), "runs": {}}
    for key, run in RUNS.items():
        pdir = args.results / "predictions" / run
        for s in ("test_long", "test"):
            check_provenance(pdir, s, args.eval_dir / f"{s}.jsonl")
        model_long, model_test = load_predictions(pdir / "test_long.jsonl"), load_predictions(pdir / "test.jsonl")
        systems = {
            "model": (model_long, model_test),
            "hybrid": ({k: merge(v, rules["test_long"].get(k, [])) for k, v in model_long.items()},
                       {k: merge(v, rules["test"].get(k, [])) for k, v in model_test.items()}),
        }
        out["runs"][key] = {}
        for sysname, (plong, ptest) in systems.items():
            rows = analyse(long_docs, parents_of, plong, ptest, enc_cache)
            # prediction from isolation: a long ALLOW doc is falsely blocked iff some component is
            allow_rows = [r for r in rows if r["gold"] == "ALLOW"]
            predicted_fb = sum(any(ptest[p.doc_id] for p in parents_of[r["doc_id"]]) for r in allow_rows)
            res = evaluate(long_docs, plong)
            out["runs"][key][sysname] = {
                "entity_f1": res["entity"]["micro"]["f1"], "confusion": res["document"]["confusion"],
                "false_block_predicted_from_components": predicted_fb, **summarise(rows), "docs": rows}
    write_json(ROOT / "reports/evidence/round2_long_docs.json", out)

    print(f"test_long: {out['n_docs']} docs {out['decisions']}, tokens {out['tokens']}, windows/doc {out['windows_per_doc']}, "
          f"components/doc {out['components_per_doc']}")
    for key, systems in out["runs"].items():
        for sysname, r in systems.items():
            print(f"{key} {sysname:6} F1 {r['entity_f1']:.3f} {r['confusion']} | FB docs {len(r['false_block_docs'])} "
                  f"(predicted from components {r['false_block_predicted_from_components']}) FA docs {r['false_allow_docs']} | "
                  f"FP {r['n_fp']} (same in isolation {r['fp_same_as_isolation']}) FN {r['n_fn']} (same in isolation {r['fn_same_as_isolation']}) | "
                  f"win2+ {r['errors_in_window_2_plus']} near-edge {r['errors_within_32_tokens_of_window_edge']} "
                  f"cross-component {r['errors_crossing_component_boundary']}")
            print(f"      FP labels {r['fp_labels']} on {r['fp_hit_negative_types']}; FN labels {r['fn_labels']}")


if __name__ == "__main__":
    main()
