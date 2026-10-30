"""Turns detector output into the safe text and the summary the frontend shows.

Every detected value is replaced by a placeholder such as [PERSON_NAME]. Output that
is not a list of entities raises DetectionFailedError; entities that cannot be masked
raise MaskingFailedError. Either way, no masked copy is produced with values left in it.
"""

import unicodedata
from collections import Counter
from dataclasses import dataclass

from backend.app.detection import DetectionFailedError, Entity, MaskingFailedError
from backend.app.labels import LABEL_PRIORITY, LABEL_TO_CODE, MODEL_LABEL_TO_CODE, SAUDI_PATTERN_HINTS, TYPE_LABELS

HINT_NOTES = dict(SAUDI_PATTERN_HINTS.values())  # hint code -> sentence shown to the user


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    type: str
    hints: tuple[str, ...] = ()  # secondary Saudi-pattern hint codes; never change the type


@dataclass(frozen=True)
class SanitizedText:
    safe_text: str
    spans: list[Span]  # Python string positions in the original text
    counts: dict[str, int]  # type code -> number of masked values, in order of first appearance


def _is_word_char(char: str) -> bool:
    # Letters and digits of any script, "_", and combining marks such as Arabic diacritics.
    return char.isalnum() or char == "_" or unicodedata.category(char).startswith("M")


def expand_to_word(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a span that starts or ends inside a word to the whole word.

    A detector can flag only part of a word, for example when the model's sub-word tokens
    split an ID written directly after an Arabic word. Masking only that part would leave the
    rest of the value visible, so the mask covers the whole word instead.
    """
    while start > 0 and _is_word_char(text[start - 1]) and _is_word_char(text[start]):
        start -= 1
    while end < len(text) and _is_word_char(text[end]) and _is_word_char(text[end - 1]):
        end += 1
    return start, end


def to_spans(text: str, entities: list[Entity]) -> list[Span]:
    """Validate the entities, map their labels to type codes and merge overlaps."""
    if not all(isinstance(entity, Entity) for entity in entities):
        raise DetectionFailedError

    candidates = []  # (start, end, code, priority, length as detected, label)
    for entity in entities:
        if not (isinstance(entity.start, int) and isinstance(entity.end, int)):
            raise MaskingFailedError
        if not 0 <= entity.start < entity.end <= len(text):
            raise MaskingFailedError
        code = LABEL_TO_CODE.get(entity.label)
        if code is None:
            raise MaskingFailedError
        start, end = expand_to_word(text, entity.start, entity.end)
        candidates.append(
            (start, end, code, LABEL_PRIORITY.get(entity.label, 0), entity.end - entity.start, entity.label))

    # Overlapping spans (including exact duplicates from different detectors) become one span
    # covering all of them, so every character any detector flagged ends up masked. Its type
    # comes from the highest-priority label (a core detector label before a Saudi rule label,
    # see labels.LABEL_PRIORITY), then the longest span as detected (before word widening),
    # then the type code, so the result never depends on detector order.
    groups: list[list[tuple]] = []
    group_end = -1
    for candidate in sorted(candidates):
        if groups and candidate[0] < group_end:
            groups[-1].append(candidate)
            group_end = max(group_end, candidate[1])
        else:
            groups.append([candidate])
            group_end = candidate[1]

    merged = []
    for group in groups:
        best = min(group, key=lambda c: (-c[3], -c[4], c[2]))
        merged.append(Span(group[0][0], max(c[1] for c in group), best[2], _hints(group, best)))
    return merged


def _hints(group: list[tuple], best: tuple) -> tuple[str, ...]:
    """Saudi patterns that the core-typed value itself also matches (secondary explanation only).

    A hint needs a core type and a Saudi match covering the whole core finding, so a Saudi match
    inside a longer value (for example "0532 0130 00" inside a spaced IBAN) gives no hint.
    """
    if best[5] not in MODEL_LABEL_TO_CODE:
        return ()
    return tuple(sorted({
        SAUDI_PATTERN_HINTS[c[5]][0] for c in group
        if c[5] in SAUDI_PATTERN_HINTS and c[2] != best[2] and c[0] <= best[0] and best[1] <= c[1]
    }))


def sanitize(text: str, entities: list[Entity]) -> SanitizedText:
    spans = to_spans(text, entities)
    parts = []
    last = 0
    for span in spans:
        parts.append(text[last:span.start])
        parts.append(f"[{span.type}]")
        last = span.end
    parts.append(text[last:])
    return SanitizedText(safe_text="".join(parts), spans=spans, counts=dict(Counter(s.type for s in spans)))


def detected_summary(counts: dict[str, int]) -> list[dict]:
    return [{"type": code, "label": TYPE_LABELS[code], "count": count} for code, count in counts.items()]


def pattern_hint_summary(spans: list[Span]) -> list[dict]:
    """Secondary hints per (primary type, pattern), in order of first appearance. No values, no positions."""
    counts = Counter((span.type, hint) for span in spans for hint in span.hints)
    return [{"type": code, "label": TYPE_LABELS[code], "pattern": hint, "note": HINT_NOTES[hint], "count": count}
            for (code, hint), count in counts.items()]


def utf16_offset(text: str, index: int) -> int:
    """Convert a Python string position to a JavaScript (UTF-16) string position.

    They differ only for characters outside the Basic Multilingual Plane, such as emoji,
    which count as one character in Python and two in JavaScript.
    """
    return index + sum(1 for char in text[:index] if ord(char) > 0xFFFF)
