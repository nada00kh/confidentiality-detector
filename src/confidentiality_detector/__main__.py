"""Command-line check: python -m confidentiality_detector --model-dir DIR [--mode M] [--file F]

Reads the text from --file or stdin and prints the decision as JSON (no text, no values).
Exit status: 0 = ALLOW, 10 = BLOCK, 2 = usage/configuration error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_POLICY = Path(__file__).resolve().parents[2] / "configs/inference/policy.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="confidentiality_detector")
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--mode", default=None)
    ap.add_argument("--file", type=Path, default=None)
    ap.add_argument("--device", default=None)
    args = ap.parse_args(argv)

    from .pipeline import ConfidentialityDetector

    if not args.policy.exists():  # the default is resolved from the source tree (editable install)
        print(json.dumps({"error": f"policy file not found: {args.policy}; pass --policy"}), file=sys.stderr)
        return 2
    try:
        detector = ConfidentialityDetector.load(args.model_dir, args.policy, device=args.device)
    except Exception as exc:
        print(json.dumps({"error": f"could not load detector: {type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 2
    text = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
    decision = detector.inspect(text, args.mode)
    print(json.dumps(decision.to_dict(), indent=2))
    return 10 if decision.blocked else 0


if __name__ == "__main__":
    sys.exit(main())
