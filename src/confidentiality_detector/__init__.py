"""Local confidentiality detector: finds the 13 target categories and returns BLOCK/ALLOW.

Text never leaves the process; decisions expose categories and character offsets only,
never the matched values. Entry points:

    from confidentiality_detector.pipeline import ConfidentialityDetector
    det = ConfidentialityDetector.load(model_dir, "configs/inference/policy.json")
    det.inspect(text).to_dict()

or the command line: python -m confidentiality_detector --model-dir <dir> < prompt.txt
"""

from .labels import TARGET_LABELS
from .policy import ALLOW, BLOCK, Decision, Finding, PolicyConfig, SecurityMode

__all__ = ["ALLOW", "BLOCK", "Decision", "Finding", "PolicyConfig", "SecurityMode", "TARGET_LABELS"]
