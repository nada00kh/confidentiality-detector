"""Character-span -> subword BIO alignment and sliding windows.

This is the single implementation shared by training-feature construction and inference.
The alignment rules reproduce notebooks/03_mbert_tokenization_and_alignment.ipynb
(build_bio2_labels / make_windows); tests/test_alignment.py checks that equivalence
against the original saved dataset.

Alignment rules, per subword token (special tokens excluded):
  * overlaps no annotation                          -> O
  * overlaps >1 annotation, or straddles a boundary -> IGNORE
  * inside an ignore span                           -> IGNORE
  * inside a negative (out-of-scope) span           -> O
  * inside a target span                            -> B-/I-<label>
and a target entity with any IGNORE token is ignored entirely, so no entity is ever
scored or trained half-labelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .documents import Document
from .labels import IGNORE_INDEX, LABEL2ID

I_LABEL_IDS = frozenset(i for label, i in LABEL2ID.items() if label.startswith("I-"))


@dataclass
class Encoded:
    input_ids: list[int]              # without special tokens
    offsets: list[tuple[int, int]]    # character offsets per token


def encode_text(tokenizer, text: str) -> Encoded:
    # The whole document is tokenised once, without truncation, to get character offsets; it is
    # never fed to the model as is. verbose=False silences the tokenizer's "sequence length is
    # longer than the specified maximum" warning for this call only: the model-input limit is
    # enforced where model inputs are built (training_features, wrap_window).
    enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False, verbose=False)
    return Encoded(list(enc["input_ids"]), [tuple(o) for o in enc["offset_mapping"]])


def token_label_ids(offsets: Sequence[tuple[int, int]], doc: Document) -> list[int]:
    annotations = (
        [(s, "target") for s in doc.spans]
        + [(s, "ignore") for s in doc.ignore_spans]
        + [(s, "negative") for s in doc.negative_spans]
    )
    labels: list[int] = []
    token_ann: list[list[int]] = []
    previous = None
    for start, end in offsets:
        matches = [i for i, (s, _) in enumerate(annotations) if start < s.end and end > s.start]
        token_ann.append(matches)
        if not matches:
            labels.append(LABEL2ID["O"])
            previous = None
            continue
        if len(matches) != 1:
            labels.append(IGNORE_INDEX)
            previous = None
            continue
        ann_id = matches[0]
        span, role = annotations[ann_id]
        if start < span.start or end > span.end or role == "ignore":
            labels.append(IGNORE_INDEX)
            previous = None
            continue
        if role == "negative":
            labels.append(LABEL2ID["O"])
            previous = None
            continue
        prefix = "I" if previous == ann_id else "B"
        labels.append(LABEL2ID[f"{prefix}-{span.label}"])
        previous = ann_id

    for ann_id, (span, role) in enumerate(annotations):
        if role != "target":
            continue
        positions = [p for p, m in enumerate(token_ann) if ann_id in m]
        valid = {LABEL2ID[f"B-{span.label}"], LABEL2ID[f"I-{span.label}"]}
        if not positions or any(labels[p] not in valid for p in positions):
            for p in positions:
                labels[p] = IGNORE_INDEX
    return labels


@dataclass(frozen=True)
class Window:
    context_start: int  # first token fed to the model
    own_start: int      # first token whose prediction/label belongs to this window
    end: int            # exclusive
    own_end: int | None = None  # exclusive end of the owned tokens; None = end

    @property
    def owned(self) -> range:
        return range(self.own_start, self.end if self.own_end is None else self.own_end)


def plan_windows(
    n_tokens: int,
    max_tokens: int,
    overlap: int,
    can_end_before: Callable[[int], bool] = lambda i: True,
) -> list[Window]:
    """Split [0, n_tokens) into windows of <= max_tokens tokens.

    Each window re-reads up to `overlap` tokens of left context that are owned by the
    previous window, so every token is owned (labelled / predicted) exactly once.
    """
    if max_tokens <= overlap:
        raise ValueError("max_tokens must exceed overlap")
    windows: list[Window] = []
    cursor = 0
    while cursor < n_tokens:
        start = max(0, cursor - overlap)
        end = min(start + max_tokens, n_tokens)
        while end < n_tokens and end > cursor and not can_end_before(end):
            end -= 1
        if end <= cursor:
            raise ValueError("Cannot place a window boundary without cutting an entity")
        windows.append(Window(start, cursor, end))
        cursor = end
    return windows


def _wrap_special(tokenizer, ids: list[int]) -> list[int]:
    """[CLS] ids [SEP] (BERT/DeBERTa) or <s> ids </s> (RoBERTa): one token on each side."""
    if tokenizer.cls_token_id is None or tokenizer.sep_token_id is None:
        raise ValueError("Tokenizer must define cls and sep tokens")
    return [tokenizer.cls_token_id] + list(ids) + [tokenizer.sep_token_id]


def training_features(
    tokenizer, doc: Document, max_length: int = 512, overlap: int = 32
) -> list[dict]:
    """Model inputs for one document (one dict per window), labels aligned to subwords."""
    enc = encode_text(tokenizer, doc.text)
    labels = token_label_ids(enc.offsets, doc)
    windows = plan_windows(
        len(enc.input_ids), max_length - 2, overlap, lambda i: labels[i] not in I_LABEL_IDS
    )
    features = []
    for w in windows:
        window_labels = labels[w.context_start:w.end]
        window_labels[: w.own_start - w.context_start] = [IGNORE_INDEX] * (w.own_start - w.context_start)
        ids = _wrap_special(tokenizer, enc.input_ids[w.context_start:w.end])
        if len(ids) > max_length:
            raise ValueError(f"model input of {len(ids)} tokens exceeds max_length={max_length}")
        features.append(
            {
                "input_ids": ids,
                "attention_mask": [1] * len(ids),
                "labels": [IGNORE_INDEX] + window_labels + [IGNORE_INDEX],
            }
        )
    return features


STITCHING = ("first", "centered")


def inference_windows(n_tokens: int, max_length: int = 512, overlap: int = 64, stitching: str = "first") -> list[Window]:
    """Windows for inference: no gold labels, so cut anywhere; predictions are stitched
    back onto the full token sequence before decoding, so entities split across a
    boundary are still decoded as one span.

    stitching="first" (round 1/2 behaviour): a token is predicted by the first window that
    contains it, so the last tokens before each cut are predicted with no right context.
    stitching="centered": each cut moves to the middle of the overlap, so every token near a
    cut is predicted by a window that has >= overlap // 2 tokens of context on both sides.
    Same windows, same model inputs; only the ownership of overlap tokens changes."""
    if stitching not in STITCHING:
        raise ValueError(f"stitching must be one of {STITCHING}")
    windows = plan_windows(n_tokens, max_length - 2, overlap)
    if stitching == "first" or len(windows) == 1:
        return windows

    def cut(w: Window) -> int:  # middle of the overlap between w and its predecessor
        return w.own_start - (w.own_start - w.context_start) // 2

    return [Window(w.context_start, w.own_start if k == 0 else cut(w), w.end,
                   None if k == len(windows) - 1 else cut(windows[k + 1]))
            for k, w in enumerate(windows)]


def wrap_window(tokenizer, input_ids: list[int], window: Window, max_length: int = 512) -> list[int]:
    ids = _wrap_special(tokenizer, input_ids[window.context_start:window.end])
    if len(ids) > max_length:
        raise ValueError(f"model input of {len(ids)} tokens exceeds max_length={max_length}")
    return ids
