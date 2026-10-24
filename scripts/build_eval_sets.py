"""Build split manifests and every evaluation set from the raw data.

Inputs : data/raw/english_pii_43k.jsonl, data/processed/mbert_splits (original split, for ids),
         data/challenge/challenge_v1.txt
Outputs: data/splits/original/{train,validation,test}.ids
         data/eval/*.jsonl + data/eval/manifest.json

Protocol (see reports/README):
  validation          original validation split, v2 gold      -> model selection / thresholds ONLY
  test                original test split, v2 gold            -> final in-distribution test
  test_unseen_context test entities whose 2-word left context never precedes that label in train
  test_unseen_value   test entities whose exact value never occurs with that label in train
  test_novel_template    test docs whose placeholder template has max TF-IDF cosine < 0.15 to train
  test_familiar_template test docs with max TF-IDF cosine >= 0.35 (contrast set)
  test_format_shift   test docs with target values re-rendered in held-out format family B
  test_long           concatenations of 8-14 test docs (> 512 subword tokens)
  validation_long     (v3) the same construction on the validation split: may inform inference settings
  challenge_v1        hand-written realistic cases (independent of the synthetic generator)
  challenge_v1_policy (v3) challenge_v1 + final person-name policy overlay (round 2)
  challenge_v1_final  (v3) challenge_v1_policy + decision F (out-of-scope API keys are negatives)
The original test split was never used for training or checkpoint selection of
checkpoint-4352, so all test_* sets are valid for that checkpoint as well.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from confidentiality_detector.challenge import apply_overlay, load_challenge  # noqa: E402
from confidentiality_detector.documents import (  # noqa: E402
    Document, Span, document_from_ai4privacy, file_sha256, load_documents, read_jsonl, save_documents,
)
from confidentiality_detector.labels import POLICIES  # noqa: E402
from confidentiality_detector.perturb import FormatPerturber  # noqa: E402


def export_original_manifests(split_dir: Path, out_dir: Path) -> dict[str, list[str]]:
    from datasets import load_from_disk

    splits = load_from_disk(str(split_dir))
    ids = {name: [str(i) for i in splits[name]["id"]] for name in ("train", "validation", "test")}
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, values in ids.items():
        (out_dir / f"{name}.ids").write_text("\n".join(values) + "\n", encoding="utf-8")
    return ids


def read_manifests(manifest_dir: Path) -> dict[str, list[str]]:
    return {
        name: (manifest_dir / f"{name}.ids").read_text(encoding="utf-8").split()
        for name in ("train", "validation", "test")
    }


def left_context(doc: Document, span: Span, n_words: int = 2) -> str:
    return " ".join(doc.text[:span.start].lower().split()[-n_words:])


def restrict(doc: Document, keep, suffix: str) -> Document | None:
    """Keep only target spans satisfying `keep`; others become ignore spans (not scored)."""
    kept = [s for s in doc.spans if keep(s)]
    if not kept:
        return None
    dropped = [s for s in doc.spans if not keep(s)]
    return Document(doc.doc_id, doc.text, kept, sorted(doc.ignore_spans + dropped), doc.negative_spans,
                    {**doc.meta, "slice": suffix})


def concat(docs: list[Document], doc_id: str, sep: str = "\n\n") -> Document:
    text, spans, ignore, negative, offset = [], [], [], [], 0
    for i, d in enumerate(docs):
        if i:
            text.append(sep)
            offset += len(sep)
        text.append(d.text)
        shift = lambda ss: [Span(s.start + offset, s.end + offset, s.label) for s in ss]  # noqa: E731
        spans += shift(d.spans)
        ignore += shift(d.ignore_spans)
        negative += shift(d.negative_spans)
        offset += len(d.text)
    doc = Document(doc_id, "".join(text), spans, ignore, negative,
                   {"source": "ai4privacy", "parents": [d.doc_id for d in docs]})
    doc.validate()
    return doc


def long_documents(source: list[Document], rng: random.Random, prefix: str) -> list[Document]:
    """Concatenations of documents up to >= 2400 characters (> 512 subword tokens; 12-18
    documents on this data). BLOCK: one PII-bearing document
    hidden among target-free ones at a random position; ALLOW: target-free documents only."""
    pos = [d for d in source if d.spans]
    neg = [d for d in source if not d.spans and not d.ignore_spans]
    rng.shuffle(pos)
    rng.shuffle(neg)
    long_docs = []
    min_chars = 2400  # ~ >512 subword tokens for BERT-style tokenizers on this data

    def fill(group: list[Document]) -> list[Document] | None:
        while sum(len(d.text) + 2 for d in group) < min_chars:
            if not neg:
                return None
            group.append(neg.pop())
        return group

    n_block = len(neg) * 6 // 10 // 14  # ~60% of the negative pool as filler for BLOCK docs
    for k in range(n_block):
        group = fill([])
        group.insert(rng.randint(0, len(group)), pos.pop())
        long_docs.append(concat(group, f"{prefix}-block-{k:03d}"))
    k = 0
    while (group := fill([])) is not None:
        long_docs.append(concat(group, f"{prefix}-allow-{k:03d}"))
        k += 1
    return long_docs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=ROOT / "data/raw/english_pii_43k.jsonl")
    ap.add_argument("--original-splits", type=Path, default=ROOT / "data/processed/mbert_splits")
    ap.add_argument("--manifests", type=Path, default=ROOT / "data/splits/original")
    ap.add_argument("--challenge", type=Path, default=ROOT / "data/challenge/challenge_v1.txt")
    ap.add_argument("--out", type=Path, default=ROOT / "data/eval")
    ap.add_argument("--overlay", type=Path, default=ROOT / "data/challenge/challenge_v1_overlay_final_policy.json")
    ap.add_argument("--final-overlay", type=Path, default=ROOT / "data/challenge/challenge_v1_overlay_final_policy_v2.json")
    ap.add_argument("--dev", type=Path, default=ROOT / "data/dev/dev_v1.txt")
    ap.add_argument("--synth", type=Path, default=ROOT / "data/synth/round2")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--policy", default="v2", choices=sorted(POLICIES),
                    help="gold-label policy (v2 = round 1 sets in data/eval; v3 = round 2 sets in data/eval_v3)")
    args = ap.parse_args()

    if (args.manifests / "test.ids").exists():
        ids = read_manifests(args.manifests)
    else:
        ids = export_original_manifests(args.original_splits, args.manifests)
    sets = {k: set(v) for k, v in ids.items()}
    assert not (sets["train"] & sets["validation"]) and not (sets["train"] & sets["test"]) and not (
        sets["validation"] & sets["test"]), "split manifests overlap"

    raw = {str(r["id"]): r for r in read_jsonl(args.raw)}
    assert set(raw) == sets["train"] | sets["validation"] | sets["test"], "manifests do not cover raw file"
    policy = POLICIES[args.policy]
    docs = {name: [document_from_ai4privacy(raw[i], policy) for i in ids[name]] for name in ids}
    train_raw = [raw[i] for i in ids["train"]]

    out = args.out
    files: dict[str, int] = {}
    files["validation"] = save_documents(out / "validation.jsonl", docs["validation"])
    files["test"] = save_documents(out / "test.jsonl", docs["test"])

    # --- entity-level slices relative to the training split --------------------------
    train_contexts, train_values, train_names = defaultdict(set), defaultdict(set), set()
    for d in docs["train"]:
        for s in d.spans:
            train_contexts[s.label].add(left_context(d, s))
            train_values[s.label].add(d.text[s.start:s.end])
            if s.label in ("FIRSTNAME", "LASTNAME"):
                train_names.add(d.text[s.start:s.end])
    unseen_ctx = [x for d in docs["test"] if (x := restrict(d, lambda s, d=d: left_context(d, s) not in train_contexts[s.label], "unseen_context"))]
    unseen_val = [x for d in docs["test"] if (x := restrict(d, lambda s, d=d: d.text[s.start:s.end] not in train_values[s.label], "unseen_value"))]
    files["test_unseen_context"] = save_documents(out / "test_unseen_context.jsonl", unseen_ctx)
    files["test_unseen_value"] = save_documents(out / "test_unseen_value.jsonl", unseen_val)

    # --- template novelty (placeholder text, TF-IDF 1-3 grams) -----------------------
    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(ngram_range=(1, 3), sublinear_tf=True)
    x_train = vec.fit_transform(r["target_text"] for r in train_raw)
    x_test = vec.transform(raw[i]["target_text"] for i in ids["test"])
    max_sim = np.concatenate([(x_test[i:i + 512] @ x_train.T).max(axis=1).toarray().ravel()
                              for i in range(0, x_test.shape[0], 512)])
    for d, sim in zip(docs["test"], max_sim):
        d.meta["max_template_sim"] = round(float(sim), 4)
    # Templates are mostly diverse already (median max-similarity ~0.19), so contrast the tails.
    novel = [d for d, sim in zip(docs["test"], max_sim) if sim < 0.15]
    familiar = [d for d, sim in zip(docs["test"], max_sim) if sim >= 0.35]
    files["test_novel_template"] = save_documents(out / "test_novel_template.jsonl", novel)
    files["test_familiar_template"] = save_documents(out / "test_familiar_template.jsonl", familiar)

    # --- held-out value formats (family B) -------------------------------------------
    perturb_b = FormatPerturber("B", excluded_names=train_names)
    shifted = [perturb_b(d) for d in docs["test"] if d.spans]
    files["test_format_shift"] = save_documents(out / "test_format_shift.jsonl", shifted)

    # --- long documents --------------------------------------------------------------
    files["test_long"] = save_documents(out / "test_long.jsonl", long_documents(docs["test"], random.Random(args.seed), "long"))
    if policy.name == "v3":
        # Same recipe on the validation split: a long-document set that MAY inform inference
        # settings (window length), unlike test_long, which is report-only.
        files["validation_long"] = save_documents(
            out / "validation_long.jsonl", long_documents(docs["validation"], random.Random(args.seed + 1), "vlong"))

    challenge = load_challenge(args.challenge)
    files["challenge_v1"] = save_documents(out / "challenge_v1.jsonl", challenge)
    if policy.name == "v3":
        # Round 2 additions: the final person-name policy applied to challenge_v1 through an
        # overlay (the frozen file is untouched), and the hand-written development set.
        overlaid = apply_overlay(challenge, args.overlay, args.challenge)
        files["challenge_v1_policy"] = save_documents(out / "challenge_v1_policy.jsonl", overlaid)
        # Post-round-2 product decision F (out-of-scope API keys count against the detector):
        # a second overlay version; challenge_v1_policy stays as round 2 evaluated it.
        if args.final_overlay.exists():
            files["challenge_v1_final"] = save_documents(
                out / "challenge_v1_final.jsonl", apply_overlay(challenge, args.final_overlay, args.challenge))
        files["dev_v1"] = save_documents(out / "dev_v1.jsonl", load_challenge(args.dev))
        # Held-out synthetic generation families (scripts/build_synth_round2.py): never trained on.
        for kind in "AB":
            path = args.synth / f"{kind}_heldout.jsonl"
            if path.exists():
                files[f"synth_{kind}_heldout"] = save_documents(out / f"synth_{kind}_heldout.jsonl", load_documents(path))

    manifest = {
        "label_policy": policy.name,
        "seed": args.seed,
        "split_manifests": {k: len(v) for k, v in ids.items()},
        "challenge_sha256": file_sha256(args.challenge),
        **({"overlay_sha256": file_sha256(args.overlay), "dev_sha256": file_sha256(args.dev)} if policy.name == "v3" else {}),
        **({"final_overlay_sha256": file_sha256(args.final_overlay)} if policy.name == "v3" and args.final_overlay.exists() else {}),
        "raw_sha256": file_sha256(args.raw),
        "sets": {
            name: {"n_docs": n, "sha256": file_sha256(out / f"{name}.jsonl")} for name, n in files.items()
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
