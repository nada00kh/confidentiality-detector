"""Compare a local copy of the frozen detector with configs/inference/frozen_system.json.

  python scripts/check_frozen_identity.py [--model-dir checkpoints/r2_e3b_positive]

Meant for a second computer, after the checkpoint folder has been copied from storage. It runs no
model and reads no evaluation data. Part by part it reports:
  * the checkpoint files: every frozen file must be present with its frozen sha256, and no other
    file may be in the folder (the frozen identity hashes the whole folder);
  * the policy file, the rules version and the inference windows;
  * the inference code, byte for byte and up to line endings. The frozen hashes are of the bytes on
    the freezing computer, where 11 files have LF and detectors/transformer.py CRLF line endings. A
    git clone writes the platform's line endings (.gitattributes: text=auto), so the bytes differ
    while the code is the same;
  * the runtime (Python and library versions); uv.lock pins the libraries, not the Python patch level.

Exit status 0 when the checkpoint, policy, rules, windows and code content match, i.e. this is the
frozen detector; 1 otherwise. `challenge_v2.py verify-frozen` is stricter: it also requires
byte-identical code and the frozen runtime, and re-runs the recorded decisions on evaluation data
that is not in Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from challenge_v2 import FROZEN, system_fingerprint  # noqa: E402

PACKAGE = ROOT / "src/confidentiality_detector"


def same_up_to_line_endings(path: Path, frozen_sha256: str) -> bool:
    lf = path.read_bytes().replace(b"\r\n", b"\n")
    return frozen_sha256 in (hashlib.sha256(lf).hexdigest(), hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest())


def compare(model_dir: Path, policy_path: Path) -> dict:
    """parts: None where a part matches the frozen record, else what differs (names and versions only)."""
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    actual = system_fingerprint(model_dir, policy_path)
    expected_files = {**frozen["model_sha256"], **frozen["checkpoint_files_sha256"]}
    actual_files = {**actual["model_sha256"], **actual["checkpoint_files_sha256"]}
    missing = sorted(expected_files.keys() - actual_files.keys())
    unexpected = sorted(actual_files.keys() - expected_files.keys())
    different = sorted(n for n in expected_files.keys() & actual_files.keys() if expected_files[n] != actual_files[n])
    files_problem = "; ".join(f"{what}: {', '.join(names)}" for what, names in
                              (("missing", missing), ("not in the frozen record", unexpected), ("sha256 differs", different)) if names)
    byte_diffs = [rel for rel, h in frozen["code_sha256"].items() if actual["code_sha256"].get(rel) != h]
    content_diffs = [rel for rel in byte_diffs if not same_up_to_line_endings(PACKAGE / rel, frozen["code_sha256"][rel])]

    def windows(record: dict) -> str:
        return f"{record['max_length']}/{record['overlap']}/{record['stitching']}"

    parts = {
        "checkpoint files": files_problem or None,
        "policy file": None if actual["policy_sha256"] == frozen["policy_sha256"] else "sha256 differs",
        "rules version": None if actual["rules_version"] == frozen["rules_version"]
        else f"{actual['rules_version']} (frozen {frozen['rules_version']})",
        "inference windows": None if windows(actual) == windows(frozen) else f"{windows(actual)} (frozen {windows(frozen)})",
        "inference code": f"content differs: {', '.join(content_diffs)}" if content_diffs else None,
    }
    runtime = {k: {"frozen": frozen["runtime"].get(k), "local": v} for k, v in actual["runtime"].items()
               if frozen["runtime"].get(k) != v}
    return {"parts": parts, "n_checkpoint_files": len(actual_files), "n_code_files": len(frozen["code_sha256"]),
            "model_sha256": actual["model_sha256"], "rules_version": actual["rules_version"], "windows": windows(actual),
            "line_endings_differ": [rel for rel in byte_diffs if rel not in content_diffs], "runtime_differs": runtime}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=Path, default=ROOT / "checkpoints/r2_e3b_positive")
    ap.add_argument("--policy", type=Path, default=ROOT / "configs/inference/policy.json")
    args = ap.parse_args()
    if not args.model_dir.is_dir():
        print(f"no checkpoint folder at {args.model_dir}")
        return 1
    r = compare(args.model_dir, args.policy)
    ok_detail = {"checkpoint files": f"{r['n_checkpoint_files']} files, "
                                     + ", ".join(f"{n} {h[:12]}…" for n, h in r["model_sha256"].items()),
                 "rules version": r["rules_version"], "inference windows": r["windows"],
                 "inference code": f"{r['n_code_files']} files" + (f" ({len(r['line_endings_differ'])} with other line "
                                   "endings than on the freezing computer)" if r["line_endings_differ"] else "")}
    for part, problem in r["parts"].items():
        print(f"{part:<18} " + (f"DIFFERS: {problem}" if problem else f"OK  {ok_detail.get(part, '')}".rstrip()))
    runtime = "; ".join(f"{k} {v['local']} (frozen {v['frozen']})" for k, v in r["runtime_differs"].items())
    print(f"{'runtime':<18} " + (f"differs: {runtime}" if runtime else "OK  same Python and library versions"))
    same = not any(r["parts"].values())
    print(f"\nSame detector as the frozen record: {'yes' if same else 'NO'}")
    reasons = [why for cond, why in ((not same, "the detector differs"),
                                     (r["line_endings_differ"], "inference-code bytes differ in line endings"),
                                     (runtime, "the runtime differs")) if cond]
    print("Byte-identical frozen environment (required by challenge_v2.py verify-frozen): "
          + ("yes" if not reasons else "no, because " + " and ".join(reasons)))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
