"""End-to-end local inspection: text -> findings -> security policy -> BLOCK/ALLOW.

    input validation -> transformer token predictions (sliding windows, stitched per
    document) -> decoding at the mode's threshold -> deterministic rules -> span
    reconciliation (hybrid.merge) -> security policy -> Decision

Everything runs in-process; nothing is sent anywhere. Logs carry decisions, reason codes,
categories, counts, input length and latency, never the text or matched values.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Sequence

from .decoding import decode
from .detectors.hybrid import DEFAULT_RULE_PRIORITY, merge
from .documents import Span
from .policy import Decision, Finding, PolicyConfig, evaluate_policy, special_decision

log = logging.getLogger("confidentiality_detector")


def reconcile(model_spans: Sequence[Span], rule_spans: Sequence[Span],
              rule_priority=DEFAULT_RULE_PRIORITY) -> list[Finding]:
    """Merge model and rule spans (no overlaps in the result) and record each span's source."""
    merged = merge(model_spans, rule_spans, rule_priority)
    model_keys = {s.key(): s for s in model_spans}
    rule_keys = {s.key(): s for s in rule_spans}
    findings = []
    for s in merged:
        in_model, in_rules = s.key() in model_keys, s.key() in rule_keys
        source = "model+rules" if in_model and in_rules else ("rules" if in_rules else "model")
        score = (model_keys.get(s.key()) or rule_keys.get(s.key())).score
        findings.append(Finding(s.start, s.end, s.label, source, score))
    return findings


class ConfidentialityDetector:
    """Local confidentiality check.

    model_detector: object with token_predictions(texts) (TransformerDetector), or None to
    run rules only. rule_detector: object with detect_batch(texts), or None.
    """

    def __init__(self, model_detector, rule_detector, policy: PolicyConfig, model_id: str = "unknown"):
        if model_detector is None and rule_detector is None:
            raise ValueError("at least one detector is required")
        self.model_detector, self.rule_detector, self.policy, self.model_id = model_detector, rule_detector, policy, model_id

    @classmethod
    def load(cls, model_dir: str | Path, policy_path: str | Path, device: str | None = None) -> "ConfidentialityDetector":
        from .detectors.rules import RuleDetector
        from .detectors.transformer import TransformerDetector

        policy = PolicyConfig.from_json(policy_path)
        # validates weights, label mapping and the window settings against the model
        model = TransformerDetector(model_dir, device=device, **policy.inference)
        return cls(model, RuleDetector(), policy, model_id=Path(model_dir).name)

    def inspect(self, text: str, mode: str | None = None) -> Decision:
        return self.inspect_batch([text], mode)[0]

    def inspect_batch(self, texts: Sequence[str], mode: str | None = None) -> list[Decision]:
        for t in texts:
            if not isinstance(t, str):
                raise TypeError(f"text must be str, got {type(t).__name__}")
        spec = self.policy.mode(mode)
        decisions: list[Decision | None] = [None] * len(texts)
        todo = []
        for i, t in enumerate(texts):
            if not t.strip():
                decisions[i] = special_decision("EMPTY_INPUT", self.policy, spec.name)
            elif len(t) > self.policy.max_chars:
                decisions[i] = special_decision("INPUT_TOO_LARGE", self.policy, spec.name)
            else:
                todo.append(i)
        t0 = time.perf_counter()
        if todo:
            batch = [texts[i] for i in todo]
            try:
                findings = self._detect(batch, spec)
            except Exception as exc:  # fail closed, never leak text into the log
                log.error("inspection error (%s); applying on_error=%s to %d text(s)",
                          type(exc).__name__, self.policy.on_error, len(batch))
                findings = None
            for j, i in enumerate(todo):
                decisions[i] = (special_decision("INSPECTION_ERROR", self.policy, spec.name) if findings is None
                                else evaluate_policy(findings[j], self.policy, spec.name))
        ms = 1000 * (time.perf_counter() - t0)
        for t, d in zip(texts, decisions):
            log.info("decision=%s reason=%s mode=%s categories=%s n_findings=%d chars=%d batch_ms=%.0f model=%s",
                     d.decision, d.reason, d.mode, ",".join(d.categories), len(d.findings), len(t), ms, self.model_id)
        return decisions

    def _detect(self, texts: list[str], spec) -> list[list[Finding]]:
        if self.model_detector is not None:
            model_spans = [decode(tp, spec.token_threshold) for tp in self.model_detector.token_predictions(texts)]
        else:
            model_spans = [[] for _ in texts]
        if self.rule_detector is not None and spec.use_rules:
            rule_spans = self.rule_detector.detect_batch(texts)
        else:
            rule_spans = [[] for _ in texts]
        return [reconcile(m, r) for m, r in zip(model_spans, rule_spans)]
