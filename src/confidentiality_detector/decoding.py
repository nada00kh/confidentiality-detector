"""Token-level predictions -> character spans.

Predictions are stored per token as (start, end, p_O, best_non_O_label_id, p_best_non_O)
so operating points (the probability mass required to call a token sensitive) can be
re-decoded offline without re-running the model.
"""

from __future__ import annotations

from typing import Sequence

from .documents import Span
from .labels import ID2LABEL

TokenPred = tuple[int, int, float, int, float]  # start, end, p_O, best_non_O_id, p_best


def tag_tokens(tokens: Sequence[TokenPred], threshold: float | None = None) -> list[str]:
    """Return a BIO tag per token.

    threshold=None -> argmax decoding (p_best > p_O).
    threshold=t    -> a token is sensitive when 1 - p_O >= t (lower t = higher recall).
    """
    tags = []
    for _, _, p_o, best_id, p_best in tokens:
        sensitive = (p_best > p_o) if threshold is None else (1.0 - p_o) >= threshold
        tags.append(ID2LABEL[best_id] if sensitive else "O")
    return tags


def spans_from_tags(
    offsets: Sequence[tuple[int, int]], tags: Sequence[str], scores: Sequence[float] | None = None
) -> list[Span]:
    """Lenient BIO decoding: an I- tag that does not continue an entity of the same type
    opens a new entity (for a leak-prevention system a malformed tag sequence must not
    silently drop a detection)."""
    spans: list[Span] = []
    cur_label, cur_start, cur_end, cur_scores = None, 0, 0, []

    def close():
        if cur_label is not None:
            score = sum(cur_scores) / len(cur_scores) if cur_scores else None
            spans.append(Span(cur_start, cur_end, cur_label, score))

    for i, ((start, end), tag) in enumerate(zip(offsets, tags)):
        if tag == "O":
            close()
            cur_label = None
            continue
        prefix, label = tag.split("-", 1)
        if prefix == "B" or label != cur_label:
            close()
            cur_label, cur_start, cur_scores = label, start, []
        cur_end = end
        if scores is not None:
            cur_scores.append(scores[i])
    close()
    return spans


def decode(tokens: Sequence[TokenPred], threshold: float | None = None) -> list[Span]:
    tags = tag_tokens(tokens, threshold)
    return spans_from_tags([(t[0], t[1]) for t in tokens], tags, [1.0 - t[2] for t in tokens])
