"""Similarity of evaluation texts to everything the models were trained on (aggregates only).

Training corpus = ai4privacy train split + round-2 synthetic training files + their
format-A augmentation shares the same templates, so the original train texts cover it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from confidentiality_detector.documents import load_documents, read_jsonl  # noqa: E402

TRAINING_SOURCES = ("data/synth/round2/A_train.jsonl", "data/synth/round2/B_train.jsonl")


def training_texts() -> list[str]:
    ids = set((ROOT / "data/splits/original/train.ids").read_text().split())
    texts = [r["source_text"] for r in read_jsonl(ROOT / "data/raw/english_pii_43k.jsonl") if str(r["id"]) in ids]
    for rel in TRAINING_SOURCES:
        if (ROOT / rel).exists():
            texts += [d.text for d in load_documents(ROOT / rel)]
    return texts


def max_similarity_to_training(texts: list[str]) -> list[float]:
    from sklearn.feature_extraction.text import TfidfVectorizer

    corpus = training_texts()
    vec = TfidfVectorizer(ngram_range=(1, 3), sublinear_tf=True, min_df=1).fit(corpus + texts)
    x_train, x = vec.transform(corpus), vec.transform(texts)
    out = []
    for i in range(0, x.shape[0], 256):
        out += (x[i:i + 256] @ x_train.T).max(axis=1).toarray().ravel().tolist()
    return out
