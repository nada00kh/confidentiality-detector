"""Security policy: turns detector findings into a BLOCK/ALLOW decision.

Detection (what spans were found, by which detector, with what score) is kept separate
from policy (what the organisation does about them). The policy is deliberately simple:

  * BLOCK if at least one finding has a label in `blocking_labels` (all 13 targets);
  * ALLOW otherwise;
  * fail closed: when the text cannot be inspected (too large, or an inspection error),
    the decision is BLOCK with an explicit reason code (`on_error`, `on_oversize`).

Explanations name categories, counts and character positions only, never values, value
shapes or lengths of the matched text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .labels import TARGET_LABELS, TARGET_SET

POLICY_VERSION = "1.0"
# Transformer inference windows (part of the deployed system, hence of this file's fingerprint).
DEFAULT_INFERENCE = {"max_length": 512, "overlap": 64, "stitching": "first"}
POLICY_FILE_KEYS = {"version", "default_mode", "blocking_labels", "max_chars", "on_error", "on_oversize", "inference", "modes"}

BLOCK, ALLOW = "BLOCK", "ALLOW"
REASONS = {
    "SENSITIVE_ENTITIES": "the text contains information in protected categories",
    "NO_SENSITIVE_ENTITIES": "no protected information was found",
    "EMPTY_INPUT": "the text is empty",
    "INPUT_TOO_LARGE": "the text is too large to inspect completely, so it is blocked by policy",
    "INSPECTION_ERROR": "the text could not be inspected, so it is blocked by policy",
}


@dataclass(frozen=True)
class SecurityMode:
    name: str
    token_threshold: float | None  # None = argmax decoding; lower = more tokens flagged
    use_rules: bool = True
    description: str = ""
    evidence: str = ""             # where the mode's numbers come from


@dataclass(frozen=True)
class PolicyConfig:
    modes: dict[str, SecurityMode]
    default_mode: str
    blocking_labels: frozenset[str] = TARGET_SET
    max_chars: int = 100_000
    on_error: str = BLOCK
    on_oversize: str = BLOCK
    version: str = POLICY_VERSION
    inference: dict = field(default_factory=lambda: dict(DEFAULT_INFERENCE))

    def __post_init__(self):
        if self.default_mode not in self.modes:
            raise ValueError(f"default mode {self.default_mode!r} is not defined")
        unknown = set(self.blocking_labels) - TARGET_SET
        if unknown:
            raise ValueError(f"blocking labels outside the 13-label scope: {sorted(unknown)}")
        if self.on_error not in (BLOCK, ALLOW) or self.on_oversize not in (BLOCK, ALLOW):
            raise ValueError("on_error / on_oversize must be BLOCK or ALLOW")
        if set(self.inference) != set(DEFAULT_INFERENCE):
            raise ValueError(f"inference settings must be exactly {sorted(DEFAULT_INFERENCE)}")

    def mode(self, name: str | None) -> SecurityMode:
        name = name or self.default_mode
        if name not in self.modes:
            raise ValueError(f"unknown security mode {name!r}; available: {sorted(self.modes)}")
        return self.modes[name]

    @classmethod
    def from_json(cls, path: str | Path) -> "PolicyConfig":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        unknown = set(raw) - POLICY_FILE_KEYS
        if unknown:  # a misspelt or retired setting must not be silently ignored
            raise ValueError(f"unknown policy settings: {sorted(unknown)}")
        modes ={name: SecurityMode(name=name, **spec) for name, spec in raw["modes"].items()}
        return cls(
            modes=modes,
            default_mode=raw["default_mode"],
            blocking_labels=frozenset(raw.get("blocking_labels", TARGET_LABELS)),
            max_chars=int(raw.get("max_chars", 100_000)),
            on_error=raw.get("on_error", BLOCK),
            on_oversize=raw.get("on_oversize", BLOCK),
            version=str(raw.get("version", POLICY_VERSION)),
            inference={**DEFAULT_INFERENCE, **raw.get("inference", {})},
        )


@dataclass(frozen=True)
class Finding:
    start: int
    end: int
    label: str
    source: str               # "model", "rules" or "model+rules"
    score: float | None = None


@dataclass(frozen=True)
class Decision:
    decision: str                       # BLOCK or ALLOW
    reason: str                         # key of REASONS
    mode: str
    categories: tuple[str, ...]
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    policy_version: str = POLICY_VERSION

    @property
    def blocked(self) -> bool:
        return self.decision == BLOCK

    def explanation(self) -> str:
        """User-facing text: categories and positions only."""
        if self.reason != "SENSITIVE_ENTITIES":
            return f"{self.decision}: {REASONS[self.reason]}."
        counts = {c: sum(f.label == c for f in self.findings) for c in self.categories}
        parts = ", ".join(f"{c} ({n})" for c, n in counts.items())
        positions = ", ".join(f"{f.start}-{f.end}" for f in self.findings)
        return f"BLOCK: {REASONS[self.reason]}: {parts}. Character positions: {positions}."

    def to_dict(self) -> dict:
        """Safe serialisation (no text, no values)."""
        return {
            "decision": self.decision, "reason": self.reason, "mode": self.mode,
            "categories": list(self.categories), "policy_version": self.policy_version,
            "findings": [{"start": f.start, "end": f.end, "label": f.label, "source": f.source,
                          "score": None if f.score is None else round(f.score, 4)} for f in self.findings],
            "explanation": self.explanation(),
        }


def evaluate_policy(findings: Iterable[Finding], config: PolicyConfig, mode: str) -> Decision:
    blocking = tuple(sorted((f for f in findings if f.label in config.blocking_labels), key=lambda f: (f.start, f.end)))
    if blocking:
        return Decision(BLOCK, "SENSITIVE_ENTITIES", mode, tuple(sorted({f.label for f in blocking})),
                        blocking, config.version)
    return Decision(ALLOW, "NO_SENSITIVE_ENTITIES", mode, (), (), config.version)


def special_decision(reason: str, config: PolicyConfig, mode: str) -> Decision:
    outcome = {"EMPTY_INPUT": ALLOW, "INPUT_TOO_LARGE": config.on_oversize, "INSPECTION_ERROR": config.on_error}[reason]
    return Decision(outcome, reason, mode, (), (), config.version)
