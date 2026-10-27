"""Adapter for the team's frozen detector in src/confidentiality_detector (mBERT + rules v3).

The frozen package is used as documented in docs/INTEGRATION.md §2 and is not modified:
it is loaded once with ConfidentialityDetector.load(...) from the local checkpoint, and
every text is inspected with the fixed mode "strict". The mode never comes from a request.
"""

import threading
from pathlib import Path

from backend.app.detection import DetectionFailedError, Entity

MODE = "strict"

# Reasons for which the frozen detector actually inspected the text, with the decision it
# gives for them (confidentiality_detector.policy.REASONS).
INSPECTED = {"SENSITIVE_ENTITIES": "BLOCK", "NO_SENSITIVE_ENTITIES": "ALLOW"}


class ModelDetector:
    def __init__(self, inspector):
        self._inspector = inspector
        # docs/INTEGRATION.md §5: the shared fast tokenizer is not verified for concurrent use.
        self._lock = threading.Lock()

    @classmethod
    def load(cls, model_dir: Path, policy_path: Path, device: str = "cpu") -> "ModelDetector":
        # A clear message instead of the transformers error for a path that is not a folder.
        if not Path(model_dir).is_dir():
            raise FileNotFoundError(f"checkpoint folder not found: {model_dir}")
        if not Path(policy_path).is_file():
            raise FileNotFoundError(f"policy file not found: {policy_path}")

        # Imported here so that importing the backend does not load torch or the model.
        from confidentiality_detector.pipeline import ConfidentialityDetector

        return cls(ConfidentialityDetector.load(model_dir, policy_path, device=device))

    def detect(self, text: str) -> list[Entity]:
        with self._lock:
            result = self._inspector.inspect(text, MODE)

        # The frozen detector fails closed by answering BLOCK without findings
        # (INSPECTION_ERROR, INPUT_TOO_LARGE). Without findings there is nothing to mask,
        # so anything but a completed, consistent inspection is a detection failure.
        expected = INSPECTED.get(result.reason)
        if expected is None or result.decision != expected or bool(result.findings) != (expected == "BLOCK"):
            raise DetectionFailedError
        return [Entity(f.start, f.end, f.label) for f in result.findings]
