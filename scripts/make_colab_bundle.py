"""Package code + data needed on Colab into a per-round bundle (no model weights), then verify it.

  python scripts/make_colab_bundle.py --round round2            # build + verify (extract, imports, pytest)
  python scripts/make_colab_bundle.py --round round2 --no-tests # build + structural checks only

Bundles: dist/colab_bundle_<round>.zip. (The round-1 bundle actually used on Colab is kept as
dist/colab_bundle_round1-r2.zip.) The builder refuses to package anything named challenge_v2:
the independent challenge set must never travel with development artefacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from colab_runner import PROJECT_IMPORTS  # noqa: E402

COMMON_INCLUDE = ["src/confidentiality_detector", "scripts", "configs", "tests", "data/splits", "data/challenge",
                  "data/raw/english_pii_43k.jsonl", "requirements-colab.txt", "pyproject.toml"]
COMMON_REQUIRED = ["requirements-colab.txt", "scripts/train.py", "scripts/predict.py", "scripts/evaluate.py",
                   "data/raw/english_pii_43k.jsonl", "data/splits/original/train.ids",
                   "data/splits/original/validation.ids", "data/splits/original/test.ids",
                   "data/challenge/challenge_v1.txt", "data/challenge/challenge_v1.sha256",
                   *[f"src/{m.replace('.', '/')}.py" for m in PROJECT_IMPORTS]]


def round_spec(name: str) -> dict:
    if name == "round2":
        from colab_round2 import BUNDLE_VERSION, ROUND2

        return {"version": BUNDLE_VERSION, "eval_dir": "data/eval_v3",
                "include": COMMON_INCLUDE + ["data/eval_v3", "data/dev", "data/synth/round2"],
                "required": COMMON_REQUIRED + ["scripts/colab_runner.py", "scripts/colab_round2.py",
                                               "data/dev/dev_v1.txt", "data/synth/round2/manifest.json",
                                               "data/synth/round2/A_train.jsonl", "data/synth/round2/B_train.jsonl",
                                               "data/challenge/challenge_v1_overlay_final_policy.json",
                                               *[s.config for s in ROUND2.stages if s.config], ROUND2.smoke_config]}
    raise SystemExit(f"unknown round {name!r}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(include: list[str]) -> list[Path]:
    files = []
    for item in include:
        path = ROOT / item
        if not path.exists():
            raise SystemExit(f"missing bundle input: {item}")
        candidates = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        files += [f for f in candidates if "__pycache__" not in f.parts and f.suffix != ".pyc"]
    leaked = [f for f in files if "challenge_v2" in f.relative_to(ROOT).as_posix().replace("challenge_v2.py", "")
              and f.name != "test_challenge_v2.py"]
    if leaked:
        raise SystemExit(f"refusing to bundle challenge_v2 material: {[str(f.relative_to(ROOT)) for f in leaked]}")
    return files


def build(out: Path, spec: dict) -> dict:
    files = collect(spec["include"])
    info = {"bundle_version": spec["version"], "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": {f.relative_to(ROOT).as_posix(): sha256(f) for f in files}}
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.relative_to(ROOT).as_posix())
        zf.writestr("BUNDLE_INFO.json", json.dumps(info, indent=2))
    return info


def verify(out: Path, info: dict, spec: dict, run_tests: bool) -> None:
    with zipfile.ZipFile(out) as zf:
        if zf.testzip() is not None:
            raise SystemExit("bundle is corrupt")
        names = set(zf.namelist())
        manifest = json.loads(zf.read(f"{spec['eval_dir']}/manifest.json"))
        required = spec["required"] + ["BUNDLE_INFO.json", f"{spec['eval_dir']}/manifest.json"]
        required += [f"{spec['eval_dir']}/{name}.jsonl" for name in manifest["sets"]]
        missing = [r for r in required if r not in names]
        if missing:
            raise SystemExit(f"bundle is missing required files: {missing}")
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            tmp = Path(tmp)
            bad = [rel for rel, digest in info["files"].items() if sha256(tmp / rel) != digest]
            if bad:
                raise SystemExit(f"extracted files differ from sources: {bad[:5]}")
            for name, meta in manifest["sets"].items():
                if sha256(tmp / spec["eval_dir"] / f"{name}.jsonl") != meta["sha256"]:
                    raise SystemExit(f"{spec['eval_dir']}/{name}.jsonl does not match its manifest")
            synth_manifest = tmp / "data/synth/round2/manifest.json"
            if synth_manifest.exists():
                for bucket, meta in json.loads(synth_manifest.read_text())["files"].items():
                    if sha256(tmp / f"data/synth/round2/{bucket}.jsonl") != meta["sha256"]:
                        raise SystemExit(f"data/synth/round2/{bucket}.jsonl does not match its manifest")
            env = {**os.environ, "PYTHONPATH": str(tmp / "src"), "PYTHONUTF8": "1"}
            probe = "import importlib\n" + "".join(f"importlib.import_module({m!r})\n" for m in PROJECT_IMPORTS)
            subprocess.run([sys.executable, "-c", probe], cwd=tmp, env=env, check=True)
            print("import check from extracted bundle: ok")
            if run_tests:
                subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=tmp, env=env, check=True)
                print("pytest from extracted bundle: ok")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="round2")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--no-tests", action="store_true")
    args = ap.parse_args()
    spec = round_spec(args.round)
    out = args.out or ROOT / f"dist/colab_bundle_{args.round}.zip"
    info = build(out, spec)
    verify(out, info, spec, run_tests=not args.no_tests)
    print(f"wrote {out} ({len(info['files'])} files, {out.stat().st_size / 1e6:.1f} MB), "
          f"bundle_version={spec['version']}, sha256={sha256(out)}")


if __name__ == "__main__":
    main()
