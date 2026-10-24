"""Target label set, BIO label mapping, and the policy that maps raw dataset labels onto it.

The BIO ordering ("O", then B-/I- pairs over the alphabetically sorted targets) is the
ordering used by the original mBERT checkpoint (checkpoint-4352). Keeping it identical
means the existing checkpoint can be loaded and validated against this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

TARGET_LABELS: tuple[str, ...] = (
    "PASSWORD",
    "USERNAME",
    "EMAIL",
    "PHONENUMBER",
    "FIRSTNAME",
    "LASTNAME",
    "SSN",
    "CREDITCARDNUMBER",
    "CREDITCARDCVV",
    "IBAN",
    "ACCOUNTNUMBER",
    "STREET",
    "IPV4",
)
TARGET_SET = frozenset(TARGET_LABELS)

BIO_LABELS: tuple[str, ...] = ("O",) + tuple(
    f"{prefix}-{entity}" for entity in sorted(TARGET_LABELS) for prefix in ("B", "I")
)
LABEL2ID: dict[str, int] = {label: i for i, label in enumerate(BIO_LABELS)}
ID2LABEL: dict[int, str] = {i: label for label, i in LABEL2ID.items()}
IGNORE_INDEX = -100

assert len(BIO_LABELS) == 27


def validate_label_mapping(id2label: dict) -> None:
    """Raise if a model config's id2label does not match BIO_LABELS exactly."""
    normalized = {int(k): v for k, v in id2label.items()}
    if normalized != ID2LABEL:
        diff = {
            i: (normalized.get(i), ID2LABEL.get(i))
            for i in set(normalized) | set(ID2LABEL)
            if normalized.get(i) != ID2LABEL.get(i)
        }
        raise ValueError(f"Model label mapping does not match BIO_LABELS: {diff}")


_IPV4 = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$")


class Role(str, Enum):
    TARGET = "target"      # supervised as B-/I-<label>, scored as a target entity
    NEGATIVE = "negative"  # out-of-scope entity: supervised as O, tracked as a hard negative
    IGNORE = "ignore"      # ambiguous w.r.t. the targets: no loss, not scored either way


@dataclass(frozen=True)
class LabelPolicy:
    """How raw ai4privacy labels map onto the 13 targets.

    name="v1_original" reproduces the original notebooks: every non-target entity is
    ignored (-100) during training.  name="v2" is the corrected policy:
      * IP entities whose value is an IPv4 address are IPV4 (the source labels ~48% of
        its generic "IP" entities with IPv4 values; they are IPv4 addresses by definition).
      * MIDDLENAME is ignored: the source frequently uses it for standalone given names,
        so labelling it O would teach the model to miss names, and labelling it FIRSTNAME
        would silently widen the scope.
      * MASKEDNUMBER is ignored: despite the name, every value is a full, unmasked 16-digit
        number (surface-identical to a card number) and ~22% follow card cues such as
        "card ending in"; labelling it O would contradict CREDITCARDNUMBER supervision.
      * every other non-target entity becomes O (hard negatives such as PIN, IPV6,
        PHONEIMEI, BIC, DATE, ...).
    """

    name: str = "v2"
    ignore_labels: frozenset[str] = frozenset({"MIDDLENAME", "MASKEDNUMBER"})
    # v3: a CREDITCARDCVV value is a target only with contextual evidence (see cvv_has_evidence);
    # without it the span is ignored (neither trained nor scored).
    cvv_requires_evidence: bool = False

    def resolve(self, label: str, value: str) -> tuple[Role, str]:
        if label in TARGET_SET:
            return Role.TARGET, label
        if self.name == "v1_original":
            return Role.IGNORE, label
        if label == "IP" and _IPV4.match(value.strip()):
            return Role.TARGET, "IPV4"
        if label in self.ignore_labels:
            return Role.IGNORE, label
        return Role.NEGATIVE, label


V1_ORIGINAL = LabelPolicy(name="v1_original", ignore_labels=frozenset())
V2 = LabelPolicy(name="v2")
V3 = LabelPolicy(name="v3", cvv_requires_evidence=True)
POLICIES = {"v1_original": V1_ORIGINAL, "v2": V2, "v3": V3}
CURRENT_POLICY = V3


# --- CREDITCARDCVV evidence (annotation policy v3) ---------------------------------------
# A 3-4 digit number is only a card verification code when the text says so. Explicit cues
# name the code; card context is a card number or an expiry date close by. The same
# definitions are used for gold labels, the rule detector and challenge validation.
# Strong cues name the card verification code unambiguously. "security code" is weak: it also
# names one-time codes and PINs, so it counts only together with card context.
CVV_STRONG_CUE = (r"cvv2?|cvc2?|ccv|csc|cvn|card[ _-]?verification(?:[ _-]?(?:value|code|number))?"
                  r"|digits? on the back|back of (?:the|your|my|this) card")
CVV_WEAK_CUE = r"security[ _-]?code"
CVV_STRONG_CUE_RE = re.compile(r"(?i)\b(?:" + CVV_STRONG_CUE + r")\b")
CVV_CUE_RE = re.compile(r"(?i)\b(?:" + CVV_STRONG_CUE + "|" + CVV_WEAK_CUE + r")\b")
CARD_NUMBER_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
CARD_WORD_RE = re.compile(r"(?i)\b(?:card|visa|master\s?card|amex|american express|discover|credit|debit)\b")
EXPIRY_RE = re.compile(r"(?i)\b(?:exp(?:iry|iration|ires)?|valid (?:thru|through|until))\b|\b(?:0[1-9]|1[0-2])\s?/\s?(?:\d{2}|20\d{2})\b")
CVV_CUE_BEFORE, CVV_CUE_AFTER, CARD_CONTEXT = 60, 40, 120


def card_context(text: str, start: int, end: int, card_spans=(), include_card_words: bool = False) -> bool:
    """A card number (annotated or pattern), an expiry date, and optionally a card word, near the value."""
    lo, hi = max(0, start - CARD_CONTEXT), min(len(text), end + CARD_CONTEXT)
    if any(s < hi and e > lo for s, e in card_spans):
        return True
    window = text[lo:start] + " " + text[end:hi]
    return bool(CARD_NUMBER_RE.search(window) or EXPIRY_RE.search(window)
                or (include_card_words and CARD_WORD_RE.search(window)))


def cvv_has_evidence(text: str, start: int, end: int, card_spans=()) -> bool:
    """True if a CVV-shaped value at text[start:end] is supported by its context:
    a strong cue nearby, or card context (card number / expiry), or a weak cue plus a card word."""
    before = text[max(0, start - CVV_CUE_BEFORE):start]
    after = text[end:end + CVV_CUE_AFTER]
    if CVV_STRONG_CUE_RE.search(before) or CVV_STRONG_CUE_RE.search(after):
        return True
    if card_context(text, start, end, card_spans):
        return True
    weak = CVV_CUE_RE.search(before) or CVV_CUE_RE.search(after)
    return bool(weak) and card_context(text, start, end, card_spans, include_card_words=True)
