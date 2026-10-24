"""Microsoft Presidio baseline (local spaCy en_core_web_lg + Presidio recognizers).

Presidio's entity inventory differs from ours; the mapping below is lossy by design:
  * PERSON is split into FIRSTNAME (first token) / LASTNAME (last token, if any) -- the
    split is a heuristic, so entity-level FIRSTNAME/LASTNAME scores understate Presidio;
    document-level and "caught_any_type" metrics are the fair comparison.
  * IP_ADDRESS is kept only for IPv4 values.
  * There is no Presidio equivalent for PASSWORD, USERNAME, CREDITCARDCVV or STREET.
"""

from __future__ import annotations

import re

from ..documents import Span

ENTITY_MAP = {
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONENUMBER",
    "US_SSN": "SSN",
    "CREDIT_CARD": "CREDITCARDNUMBER",
    "IBAN_CODE": "IBAN",
    "IP_ADDRESS": "IPV4",
    "US_BANK_NUMBER": "ACCOUNTNUMBER",
    "PERSON": "PERSON",
}
_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


class PresidioDetector:
    name = "presidio"

    def __init__(self, score_threshold: float = 0.35, spacy_model: str = "en_core_web_lg"):
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        provider = NlpEngineProvider(
            nlp_configuration={"nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": spacy_model}]}
        )
        self.engine = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
        self.score_threshold = score_threshold

    def detect(self, text: str) -> list[Span]:
        results = self.engine.analyze(
            text=text, language="en", entities=list(ENTITY_MAP), score_threshold=self.score_threshold
        )
        spans: list[Span] = []
        for r in results:
            label = ENTITY_MAP[r.entity_type]
            value = text[r.start:r.end]
            if label == "IPV4" and not _IPV4.match(value):
                continue
            if label == "PERSON":
                spans.extend(_split_person(text, r.start, r.end, r.score))
            else:
                spans.append(Span(r.start, r.end, label, r.score))
        # Presidio can return overlapping results from different recognizers; keep the best.
        spans.sort(key=lambda s: (-(s.score or 0), -(s.end - s.start)))
        kept: list[Span] = []
        for s in spans:
            if not any(s.overlaps(k) for k in kept):
                kept.append(s)
        return sorted(kept)

    def detect_batch(self, texts: list[str]) -> list[list[Span]]:
        return [self.detect(t) for t in texts]


def _split_person(text: str, start: int, end: int, score: float) -> list[Span]:
    tokens = [(m.start() + start, m.end() + start) for m in re.finditer(r"[^\s]+", text[start:end])]
    tokens = [(s, e) for s, e in tokens if not re.fullmatch(r"(?i)(mr|mrs|ms|dr|prof|sir)\.?", text[s:e])]
    if not tokens:
        return []
    out = [Span(tokens[0][0], tokens[0][1], "FIRSTNAME", score)]
    if len(tokens) > 1:
        out.append(Span(tokens[-1][0], tokens[-1][1], "LASTNAME", score))
    return out
