from pathlib import Path

import pytest

from confidentiality_detector.alignment import (
    I_LABEL_IDS, inference_windows, plan_windows, token_label_ids, training_features,
)
from confidentiality_detector.documents import Document, Span, document_from_ai4privacy
from confidentiality_detector.labels import IGNORE_INDEX, LABEL2ID, V1_ORIGINAL, V2

ROOT = Path(__file__).resolve().parents[1]
MODEL = "google-bert/bert-base-multilingual-cased"


@pytest.fixture(scope="module")
def tokenizer():
    transformers = pytest.importorskip("transformers")
    try:
        return transformers.AutoTokenizer.from_pretrained(MODEL)
    except Exception as exc:  # offline without cache
        pytest.skip(f"tokenizer unavailable: {exc}")


def test_label_mapping_matches_original_checkpoint_order():
    assert LABEL2ID["O"] == 0
    assert LABEL2ID["B-ACCOUNTNUMBER"] == 1 and LABEL2ID["I-USERNAME"] == 26


@pytest.mark.parametrize("split", ["validation", "test"])
def test_reproduces_original_tokenized_dataset(tokenizer, split):
    """training_features(policy=v1_original) must equal notebooks/03 output exactly."""
    datasets = pytest.importorskip("datasets")
    raw_dir, tok_dir = ROOT / "data/processed/mbert_splits", ROOT / "data/processed/mbert_tokenized"
    if not raw_dir.exists() or not tok_dir.exists():
        pytest.skip("original processed datasets not present")
    records = datasets.load_from_disk(str(raw_dir))[split]
    windows = datasets.load_from_disk(str(tok_dir))[split]
    row = 0
    for record in records:
        doc = document_from_ai4privacy(record, V1_ORIGINAL)
        for feature in training_features(tokenizer, doc, max_length=512, overlap=32):
            expected = windows[row]
            assert feature["input_ids"] == expected["input_ids"], record["id"]
            assert feature["labels"] == expected["labels"], record["id"]
            row += 1
    assert row == len(windows)


def test_v2_policy_labels_negatives_as_O_and_remaps_ipv4(tokenizer):
    record = {
        "id": 1,
        "source_text": "PIN 4471 from 10.0.0.5 for Jordan",
        "privacy_mask": [
            {"value": "4471", "start": 4, "end": 8, "label": "PIN"},
            {"value": "10.0.0.5", "start": 14, "end": 22, "label": "IP"},
            {"value": "Jordan", "start": 27, "end": 33, "label": "MIDDLENAME"},
        ],
    }
    v1 = document_from_ai4privacy(record, V1_ORIGINAL)
    v2 = document_from_ai4privacy(record, V2)
    assert [s.label for s in v2.spans] == ["IPV4"]
    assert [s.label for s in v2.negative_spans] == ["PIN"]
    assert [s.label for s in v2.ignore_spans] == ["MIDDLENAME"]
    enc = tokenizer(record["source_text"], add_special_tokens=False, return_offsets_mapping=True)
    l1 = token_label_ids(enc["offset_mapping"], v1)
    l2 = token_label_ids(enc["offset_mapping"], v2)
    pin_tokens = [i for i, (s, e) in enumerate(enc["offset_mapping"]) if s >= 4 and e <= 8]
    assert all(l1[i] == IGNORE_INDEX for i in pin_tokens)       # original: hidden
    assert all(l2[i] == LABEL2ID["O"] for i in pin_tokens)      # v2: hard negative
    ip_tokens = [i for i, (s, e) in enumerate(enc["offset_mapping"]) if s >= 14 and e <= 22]
    assert l2[ip_tokens[0]] == LABEL2ID["B-IPV4"]
    assert all(l2[i] == LABEL2ID["I-IPV4"] for i in ip_tokens[1:])


def test_straddling_token_ignores_whole_entity():
    doc = Document("d", "abcdef", [Span(2, 6, "PASSWORD")])
    labels = token_label_ids([(0, 3), (3, 6)], doc)  # first token straddles the entity start
    assert labels == [IGNORE_INDEX, IGNORE_INDEX]


@pytest.mark.parametrize("n,max_tokens,overlap", [(1, 10, 2), (10, 10, 2), (11, 10, 2), (1000, 510, 32), (1000, 510, 64)])
def test_windows_own_every_token_exactly_once(n, max_tokens, overlap):
    windows = plan_windows(n, max_tokens, overlap)
    owned = [t for w in windows for t in range(w.own_start, w.end)]
    assert owned == list(range(n))
    assert all(w.end - w.context_start <= max_tokens for w in windows)
    assert all(w.own_start - w.context_start <= overlap for w in windows)


@pytest.mark.parametrize("n,max_length,overlap", [(1, 512, 64), (510, 512, 64), (511, 512, 64), (942, 512, 64),
                                                  (2000, 512, 64), (700, 128, 32), (5000, 256, 64)])
def test_centered_stitching_gives_context_on_both_sides(n, max_length, overlap):
    first = inference_windows(n, max_length, overlap, "first")
    centered = inference_windows(n, max_length, overlap, "centered")
    # same model inputs; every token still predicted exactly once
    assert [(w.context_start, w.end) for w in first] == [(w.context_start, w.end) for w in centered]
    assert [t for w in centered for t in w.owned] == list(range(n))
    assert [t for w in first for t in w.owned] == list(range(n))

    def context(w, t):
        return min(t - w.context_start, w.end - 1 - t)

    for w in first[:-1]:  # round-2 stitching: the last token before every cut has no right context
        assert w.end - 1 - max(w.owned) == 0
    for k, w in enumerate(centered):  # centered: >= overlap // 2 - 1 tokens on both sides, except at document ends
        lo = w.own_start if k else overlap // 2
        hi = max(w.owned) if k < len(centered) - 1 else n - 1 - overlap // 2
        assert all(context(w, t) >= overlap // 2 - 1 for t in range(lo, hi + 1))
    with pytest.raises(ValueError):
        inference_windows(n, max_length, overlap, "middle")


def test_training_windows_do_not_cut_entities():
    labels = [0] * 8 + [LABEL2ID["B-IBAN"]] + [LABEL2ID["I-IBAN"]] * 4 + [0] * 5
    windows = plan_windows(len(labels), 10, 2, lambda i: labels[i] not in I_LABEL_IDS)
    for w in windows:
        assert w.end == len(labels) or labels[w.end] not in I_LABEL_IDS
