"""The interface between the API and a detector.

A detector receives the employee's text and returns the sensitive values it found as
character positions plus the detector's own label. It never returns or stores the
values themselves; the sanitizer uses the positions to replace them.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Entity:
    start: int  # index of the first character, as in Python's text[start:end]
    end: int  # index just after the last character
    label: str  # detector label, e.g. "FIRSTNAME" (see labels.MODEL_LABEL_TO_CODE)


class Detector(Protocol):
    def detect(self, text: str) -> list[Entity]: ...


class CombinedDetector:
    """Runs several detectors on the same text and returns all of their entities.

    If any detector fails, the whole detection fails: a partial result could miss values
    the failed detector would have found. Overlaps and duplicates are resolved by the sanitizer.
    """

    def __init__(self, *detectors: Detector):
        self.detectors = detectors

    def detect(self, text: str) -> list[Entity]:
        entities: list[Entity] = []
        for detector in self.detectors:
            entities.extend(detector.detect(text))
        return entities


class DetectorUnavailableError(Exception):
    """No detector is connected, so the text cannot be checked."""


class DetectionFailedError(Exception):
    """The detector failed or returned output that cannot be trusted at all."""


class MaskingFailedError(Exception):
    """The detector reported findings, but they cannot be masked (bad positions or an unknown label)."""
