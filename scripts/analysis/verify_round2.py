"""Integrity checks for an extracted round-2 results archive, before any analysis.

  python scripts/analysis/verify_round2.py --results results/round2   ->  reports/evidence/round2_integrity.json

Checks, per run and evaluation set:
  * archive manifest: every file present with the recorded sha256;
  * bundle: the code that ran on Colab is byte-identical to this repository;
  * provenance: predictions were made on exactly the local evaluation file (sha256);
  * coverage: one prediction row per document, no unknown ids, spans inside the text,
    in-scope labels, no duplicated or overlapping predicted spans;
  * metrics: the archived (model-only) metrics are recomputed from predictions + gold;
  * data versions: training data, splits and evaluation manifest match the local files;
  * one-factor design: each run's training config differs from its parent's in one factor;
  * R0: the round-2 baseline predictions equal the round-1 E2 predictions wherever the
    evaluation texts are unchanged (i.e. the intended checkpoint was used).
Prints aggregates only (no document text).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.decoding import decode  # noqa: E402
from confidentiality_detector.documents import file_sha256, load_documents, read_jsonl  # noqa: E402
from confidentiality_detector.labels import TARGET_LABELS  # noqa: E402
from confidentiality_detector.metrics import evaluate  # noqa: E402
from confidentiality_detector.runio import check_provenance, load_predictions, write_json  # noqa: E402

RUNS = {"R0": "e2_mbert_v2_fmtA", "R1": "r2_e2_v3", "R2": "r2_e3a_hardneg", "R3": "r2_e3b_positive", "R4": "r2_e4_combined"}
PARENT = {"R2": "R1", "R3": "R1", "R4": "R1"}
IGNORED_CONFIG_KEYS = {"name", "description"}


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_archive(results: Path) -> dict:
    manifest = json.loads((results / "RESULTS_MANIFEST.json").read_text(encoding="utf-8"))
    bad = [f for f, info in manifest["files"].items()
           if not (results / f).exists() or sha(results / f) != info["sha256"]]
    import zipfile

    bundle = json.loads((results / "BUNDLE_INFO.json").read_text(encoding="utf-8"))
    recorded = {f: (info["sha256"] if isinstance(info, dict) else info) for f, info in bundle["files"].items()}
    shipped = ROOT / "dist/colab_bundle_round2.zip"  # the archive that was uploaded (immutable)
    vs_shipped = None
    if shipped.exists():
        with zipfile.ZipFile(shipped) as z:
            names = {n.split("/", 1)[-1] if n.startswith("cd2/") else n: n for n in z.namelist()}
            vs_shipped = [f for f, h in recorded.items()
                          if f not in names or hashlib.sha256(z.read(names[f])).hexdigest() != h]
    changed_since = [f for f, h in recorded.items() if not (ROOT / f).exists() or sha(ROOT / f) != h]
    return {"n_files": len(manifest["files"]), "bad_files": bad, "complete": manifest["complete"], "smoke": manifest["smoke"],
            "stages": manifest["stages"], "bundle_version": bundle["bundle_version"], "bundle_files": len(bundle["files"]),
            "bundle_files_differing_from_shipped_zip": vs_shipped,
            "repo_files_changed_since_the_run": changed_since}


def check_predictions(path: Path, docs) -> dict:
    by_id = {d.doc_id: d for d in docs}
    rows = list(read_jsonl(path))
    ids = [r["doc_id"] for r in rows]
    problems = Counter()
    uncovered_chars = 0
    for r in rows:
        d = by_id.get(r["doc_id"])
        if d is None:
            problems["unknown_doc_id"] += 1
            continue
        spans = sorted((s[0], s[1], s[2]) for s in r["spans"])
        if "tokens" in r:
            tokens = [(t[0], t[1]) for t in r["tokens"]]
            if tokens != sorted(tokens) or any(a[1] > b[0] for a, b in zip(tokens, tokens[1:])):
                problems["tokens_unordered_or_overlapping"] += 1
            covered = bytearray(len(d.text))
            for s, e in tokens:
                covered[s:e] = b"\x01" * (e - s)
            missed = sum(1 for i, ch in enumerate(d.text) if not covered[i] and not ch.isspace())
            if missed:
                problems["docs_with_uncovered_chars"] += 1
                uncovered_chars += missed
            if sorted((s.start, s.end, s.label) for s in decode([tuple(t) for t in r["tokens"]], None)) != spans:
                problems["stored_spans_differ_from_redecoded"] += 1
        else:
            problems["no_token_probabilities"] += 1
        for start, end, label in spans:
            if not 0 <= start < end <= len(d.text):
                problems["span_out_of_bounds"] += 1
            if label not in TARGET_LABELS:
                problems["out_of_scope_label"] += 1
            if d.text[start:end] != d.text[start:end].strip():
                problems["span_with_outer_whitespace"] += 1
        if len(set(spans)) != len(spans):
            problems["duplicated_span"] += 1
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            problems["overlapping_spans"] += 1
    if uncovered_chars:
        problems["uncovered_non_space_chars"] = uncovered_chars
    return {"n_rows": len(rows), "n_docs": len(docs), "missing": len(set(by_id) - set(ids)),
            "duplicate_rows": len(ids) - len(set(ids)), **problems}


def compare_metrics(recomputed: dict, archived: dict) -> list[str]:
    diffs = []
    for key in ("precision", "recall", "f1", "tp", "fp", "fn"):
        a, b = recomputed["entity"]["micro"].get(key), archived["entity"]["micro"].get(key)
        if a != b and not (isinstance(a, float) and isinstance(b, float) and abs(a - b) < 1e-9):
            diffs.append(f"entity.{key}: {b} -> {a}")
    if recomputed["document"]["confusion"] != archived["document"]["confusion"]:
        diffs.append(f"document.confusion: {archived['document']['confusion']} -> {recomputed['document']['confusion']}")
    return diffs


def same_predictions(a: Path, b: Path) -> dict:
    pa, pb = load_predictions(a), load_predictions(b)
    common = set(pa) & set(pb)
    differ = sum(1 for k in common if sorted((s.start, s.end, s.label) for s in pa[k]) != sorted((s.start, s.end, s.label) for s in pb[k]))
    return {"n_common": len(common), "n_differ": differ}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval_v3")
    ap.add_argument("--round1-e2", type=Path, default=ROOT / "predictions_v3/e2_round1_on_v3")
    args = ap.parse_args()
    out: dict = {"archive": check_archive(args.results), "runs": {}}
    # The evaluation manifest as round 2 used it (sets added afterwards are listed in manifest.json only).
    round2_manifest = args.eval_dir / "manifest_round2.json"
    if not round2_manifest.exists():
        round2_manifest = args.eval_dir / "manifest.json"
    sets = list(json.loads(round2_manifest.read_text(encoding="utf-8"))["sets"])
    docs = {s: load_documents(args.eval_dir / f"{s}.jsonl") for s in sets}

    for key, run in RUNS.items():
        pred_dir = args.results / "predictions" / run
        archived = json.loads((args.results / "reports/runs" / run / "metrics.json").read_text(encoding="utf-8"))["sets"]
        info = json.loads((pred_dir / "run_info.json").read_text(encoding="utf-8"))
        run_out = {"model_dir": Path(info["model_dir"]).name, "max_length": info["args"]["max_length"],
                   "overlap": info["args"]["overlap"], "sets": {}}
        for s in sets:
            entry: dict = {}
            try:
                check_provenance(pred_dir, s, args.eval_dir / f"{s}.jsonl")
                entry["provenance"] = "ok"
            except Exception as exc:  # report, do not stop
                entry["provenance"] = f"FAILED: {exc}"
            entry["coverage"] = check_predictions(pred_dir / f"{s}.jsonl", docs[s])
            entry["metric_diffs"] = compare_metrics(evaluate(docs[s], load_predictions(pred_dir / f"{s}.jsonl")), archived[s])
            run_out["sets"][s] = entry
        summary_path = args.results / "checkpoint_meta" / run / "training_summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            dv = summary["data_versions"]
            run_out["training"] = {
                "config": summary["config"], "best_checkpoint": summary["best_checkpoint"],
                "reload_ok": summary["reload_ok"], "n_train_docs": summary["n_train_docs"],
                "n_windows": summary["n_windows"], "n_augmented": summary["n_augmented"],
                "eval_manifest_matches_local": dv["eval_manifest_sha256"] == file_sha256(round2_manifest),
                "extra_train_matches_local": {f: rec["sha256"] == file_sha256(ROOT / f) for f, rec in dv.get("extra_train", {}).items()},
                "raw_sha256": dv["raw_sha256"], "split_manifest_sha256": dv["split_manifest_sha256"],
            }
        out["runs"][key] = run_out

    configs = {k: {c: v for c, v in r["training"]["config"].items() if c not in IGNORED_CONFIG_KEYS}
               for k, r in out["runs"].items() if "training" in r}
    out["one_factor"] = {}
    for child, parent in PARENT.items():
        keys = set(configs[child]) | set(configs[parent])
        out["one_factor"][f"{child} vs {parent}"] = {k: [configs[parent].get(k), configs[child].get(k)]
                                                      for k in sorted(keys) if configs[parent].get(k) != configs[child].get(k)}
    out["one_factor"]["R1 vs E2 (round 1)"] = "see round-1 summary; checked in the report"
    data_ids = {k: (r["training"]["raw_sha256"], json.dumps(r["training"]["split_manifest_sha256"], sort_keys=True))
                for k, r in out["runs"].items() if "training" in r}
    out["same_raw_data_and_split"] = len(set(data_ids.values())) == 1

    out["r0_equals_round1_e2"] = {}
    for s in sets:
        r1 = args.round1_e2 / f"{s}.jsonl"
        if r1.exists():
            out["r0_equals_round1_e2"][s] = same_predictions(args.results / "predictions" / RUNS["R0"] / f"{s}.jsonl", r1)

    write_json(ROOT / "reports/evidence/round2_integrity.json", out)
    a = out["archive"]
    print(f"archive: {a['n_files']} files, bad {len(a['bad_files'])}, complete={a['complete']}, smoke={a['smoke']}, "
          f"stages={a['stages']}; bundle {a['bundle_version']} ({a['bundle_files']} files), "
          f"differing from the shipped zip: {a['bundle_files_differing_from_shipped_zip']}; repo files changed since: {a['repo_files_changed_since_the_run']}")
    for key, r in out["runs"].items():
        prov = sum(e["provenance"] == "ok" for e in r["sets"].values())
        cov_problems = {s: {k: v for k, v in e["coverage"].items() if k not in ("n_rows", "n_docs") and v}
                        for s, e in r["sets"].items()}
        cov_problems = {s: v for s, v in cov_problems.items() if v}
        diffs = {s: e["metric_diffs"] for s, e in r["sets"].items() if e["metric_diffs"]}
        print(f"{key} {RUNS[key]}: model_dir={r['model_dir']} window={r['max_length']}/{r['overlap']} "
              f"provenance ok {prov}/{len(r['sets'])}; coverage problems {cov_problems or 'none'}; metric diffs {diffs or 'none'}")
        if "training" in r:
            t = r["training"]
            print(f"   train docs {t['n_train_docs']} windows {t['n_windows']} augmented {t['n_augmented']} best {t['best_checkpoint']} "
                  f"reload_ok {t['reload_ok']} eval_manifest_local {t['eval_manifest_matches_local']} extra {t['extra_train_matches_local']}")
    print("one-factor diffs:", json.dumps(out["one_factor"], indent=1))
    print("same raw data and split for R1-R4:", out["same_raw_data_and_split"])
    print("R0 vs round-1 E2 predictions (unchanged texts):", out["r0_equals_round1_e2"])


if __name__ == "__main__":
    main()
