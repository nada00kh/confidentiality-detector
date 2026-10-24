"""Model + rules span reconciliation: union of the model and the deterministic rules.

Where a rule span and a model span overlap, the rule span wins for labels in
`rule_priority_labels` (structured identifiers with validator-backed boundaries) and the
model span wins otherwise. Non-overlapping spans from either source are kept, so the union
can only add detections relative to the model alone (recall-oriented by construction).
"""

from __future__ import annotations

from typing import Iterable, Sequence

from ..documents import Span

DEFAULT_RULE_PRIORITY = frozenset({"EMAIL", "IPV4", "IBAN", "CREDITCARDNUMBER", "SSN"})


def merge(
    model_spans: Sequence[Span],
    rule_spans: Sequence[Span],
    rule_priority_labels: Iterable[str] = DEFAULT_RULE_PRIORITY,
    rule_labels: Iterable[str] | None = None,
) -> list[Span]:
    priority = set(rule_priority_labels)
    allowed = set(rule_labels) if rule_labels is not None else None
    rules = [r for r in rule_spans if allowed is None or r.label in allowed]
    winners_from_rules = [r for r in rules if r.label in priority]
    kept_model = [m for m in model_spans if not any(m.overlaps(r) for r in winners_from_rules)]
    out = list(kept_model)
    for r in rules:
        if r in winners_from_rules or not any(r.overlaps(m) for m in kept_model):
            if not any(r.overlaps(o) for o in out):
                out.append(r)
    return sorted(out)
