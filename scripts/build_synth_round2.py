"""Generate the round-2 synthetic data (experiment A hard negatives, B difficult positives).

  python scripts/build_synth_round2.py      ->  data/synth/round2/{A_train,B_train,A_heldout,B_heldout}.jsonl + manifest.json

Gates (the script fails instead of writing questionable data):
  * every document passes synth.validate_synthetic (scope, CVV evidence, no unannotated names);
  * exact duplicates are removed;
  * contamination guard: generated documents whose TF-IDF cosine to any dev_v1 or
    challenge_v1 case is >= --max-sim are dropped, and no generated target value may equal
    a dev/challenge target value;
  * the name pool excludes every name used in dev_v1, challenge_v1 and format family B.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from confidentiality_detector.challenge import load_challenge  # noqa: E402
from confidentiality_detector.documents import file_sha256, save_documents  # noqa: E402
from confidentiality_detector.perturb import FIRST_NAMES_B, LAST_NAMES_B  # noqa: E402
from confidentiality_detector.synth import (  # noqa: E402
    FAMILIES, FIRST_NAMES_C, GENERATOR_VERSION, LAST_NAMES_C, generate, split_families, validate_synthetic,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "data/synth/round2")
    ap.add_argument("--per-family", type=int, default=160)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--max-sim", type=float, default=0.5)
    ap.add_argument("--dev", type=Path, default=ROOT / "data/dev/dev_v1.txt")
    ap.add_argument("--challenge", type=Path, default=ROOT / "data/challenge/challenge_v1.txt")
    args = ap.parse_args()

    held_out = load_challenge(args.dev) + load_challenge(args.challenge)
    held_out_names = {d.text[s.start:s.end].lower() for d in held_out for s in d.spans if s.label in ("FIRSTNAME", "LASTNAME")}
    held_out_names |= {n.lower() for n in FIRST_NAMES_B + LAST_NAMES_B}
    names = ([n for n in FIRST_NAMES_C if n.lower() not in held_out_names],
             [n for n in LAST_NAMES_C if n.lower() not in held_out_names])
    held_out_values = {d.text[s.start:s.end] for d in held_out for s in d.spans}

    out = generate(args.per_family, args.seed, names)
    report: dict = {"generator": GENERATOR_VERSION, "seed": args.seed, "per_family": args.per_family,
                    "name_pool": {"first": len(names[0]), "last": len(names[1]),
                                  "removed_as_held_out": len(FIRST_NAMES_C) + len(LAST_NAMES_C) - len(names[0]) - len(names[1])},
                    "family_split": split_families(), "buckets": {}}

    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(ngram_range=(1, 3), sublinear_tf=True).fit([d.text for d in held_out] + [d.text for docs in out.values() for d in docs])
    x_held = vec.transform([d.text for d in held_out])

    cleaned = {}
    for bucket, docs in out.items():
        problems = Counter(p for d in docs for p in validate_synthetic(d, names))
        if problems:
            raise SystemExit(f"{bucket}: annotation-policy violations {problems.most_common(5)}")
        seen, unique = set(), []
        for d in docs:
            if d.text not in seen:
                seen.add(d.text)
                unique.append(d)
        sims = (vec.transform([d.text for d in unique]) @ x_held.T).max(axis=1).toarray().ravel()
        value_clash = [d for d in unique if any(d.text[s.start:s.end] in held_out_values for s in d.spans)]
        kept = [d for d, sim in zip(unique, sims) if sim < args.max_sim and d not in value_clash]
        cleaned[bucket] = kept
        report["buckets"][bucket] = {
            "generated": len(docs), "after_dedup": len(unique), "dropped_contamination": int((sims >= args.max_sim).sum()),
            "dropped_value_clash": len(value_clash), "kept": len(kept),
            "max_sim_to_dev_or_challenge": {"median": float(np.median(sims)), "p99": float(np.quantile(sims, 0.99)), "max": float(sims.max())},
            "docs_with_targets": sum(bool(d.spans) for d in kept),
            "target_labels": dict(Counter(s.label for d in kept for s in d.spans)),
            "negative_types": dict(Counter(s.label for d in kept for s in d.negative_spans)),
            "families": len({d.meta["family"] for d in kept}),
            "distinct_templates": len({(d.meta["family"], d.meta["template_index"]) for d in kept}),
        }

    # How different are held-out families from the training families?
    for kind in "AB":
        tr, ho = cleaned[f"{kind}_train"], cleaned[f"{kind}_heldout"]
        s = (vec.transform([d.text for d in ho]) @ vec.transform([d.text for d in tr]).T).max(axis=1).toarray().ravel()
        report["buckets"][f"{kind}_heldout"]["max_sim_to_train"] = {"median": float(np.median(s)), "p90": float(np.quantile(s, 0.9))}

    args.out.mkdir(parents=True, exist_ok=True)
    report["files"] = {}
    for bucket, docs in cleaned.items():
        path = args.out / f"{bucket}.jsonl"
        save_documents(path, docs)
        report["files"][bucket] = {"n_docs": len(docs), "sha256": file_sha256(path)}
    report["dev_sha256"], report["challenge_sha256"] = file_sha256(args.dev), file_sha256(args.challenge)
    report["n_families"], report["n_templates"] = len(FAMILIES), sum(len(v) for v in FAMILIES.values())
    (args.out / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: {kk: v[kk] for kk in ("generated", "kept", "dropped_contamination", "dropped_value_clash", "families", "distinct_templates")}
                      for k, v in report["buckets"].items()}, indent=1))
    print("held-out max-sim to train:", {k: v.get("max_sim_to_train") for k, v in report["buckets"].items() if "heldout" in k})
    print("max-sim to dev/challenge:", {k: v["max_sim_to_dev_or_challenge"] for k, v in report["buckets"].items()})


if __name__ == "__main__":
    main()
