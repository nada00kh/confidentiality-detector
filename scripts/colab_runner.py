"""Fail-fast, spec-driven orchestration of GPU experiment rounds on Colab (round 2 onward).

Same guarantees as the (frozen) round-1 orchestrator scripts/colab_round1.py, generalised:
  * every external step is a subprocess with an explicit exit-code check (no shell pipes),
    streamed to the console and to <out>/logs/<stage>_<step>.log; an interrupt kills the child;
  * a stage records <out>/status/<stage>.json = ok only after its artifacts validate
    (prediction row counts per eval set, finite metrics, label mapping, reload_ok);
  * completed stages are skipped on re-run (safe resumption), interrupted ones restart clean;
  * packaging re-validates every stage and refuses to call an incomplete round complete.
A round is described by a RoundSpec (scripts/colab_round2.py).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import zipfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_IMPORTS = ("torch", "transformers", "numpy", "sklearn", "safetensors", "seqeval", "phonenumbers", "pytest")
PROJECT_IMPORTS = (
    "confidentiality_detector.labels", "confidentiality_detector.alignment", "confidentiality_detector.metrics",
    "confidentiality_detector.decoding", "confidentiality_detector.perturb", "confidentiality_detector.challenge",
    "confidentiality_detector.synth", "confidentiality_detector.policy", "confidentiality_detector.pipeline",
    "confidentiality_detector.detectors.transformer", "confidentiality_detector.detectors.hybrid",
    "confidentiality_detector.detectors.rules",
)


class StageError(RuntimeError):
    """A pipeline step failed; the message names the stage, step, exit code and log file."""


@dataclass(frozen=True)
class StageSpec:
    key: str
    run: str                       # predictions/reports name
    title: str
    config: str | None = None      # training config; None = predict with an existing model
    model: str | None = None       # key into Context.models for predict-only stages


@dataclass(frozen=True)
class RoundSpec:
    name: str
    bundle_version: str
    eval_dir: str                  # relative to the bundle root
    stages: tuple[StageSpec, ...]
    smoke_config: str
    smoke_sets: tuple[str, ...]

    def stage(self, key: str) -> StageSpec:
        for s in self.stages:
            if s.key == key:
                return s
        raise ValueError(f"unknown stage {key!r}; stages: {[s.key for s in self.stages]}")


@dataclass
class Context:
    spec: RoundSpec
    work: Path                     # extracted bundle
    out: Path                      # persistent output dir (Drive)
    models: dict = field(default_factory=dict)  # name -> existing checkpoint dir (read-only)
    train_dir: Path = Path("/content/runs")
    smoke: bool = False
    extra_env: dict = field(default_factory=dict)

    def __post_init__(self):
        self.work, self.out, self.train_dir = Path(self.work), Path(self.out), Path(self.train_dir)
        self.models = {k: Path(v) for k, v in self.models.items()}

    @property
    def eval_dir(self) -> Path:
        return self.work / self.spec.eval_dir

    @property
    def sets(self) -> tuple:
        if self.smoke:
            return self.spec.smoke_sets
        return tuple(json.loads((self.eval_dir / "manifest.json").read_text())["sets"])

    def path(self, *parts) -> Path:
        return self.out.joinpath(*parts)


# --------------------------------------------------------------------------- execution

def _env(ctx: Context) -> dict:
    env = dict(os.environ)
    env.update({"PYTHONUNBUFFERED": "1", "TOKENIZERS_PARALLELISM": "false", "HF_HUB_DISABLE_TELEMETRY": "1",
                "PYTHONPATH": str(ctx.work / "src")})
    env.update(ctx.extra_env)
    return env


def _echo(line: str) -> None:
    try:
        print(line, end="", flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc), end="", flush=True)


def run_step(ctx: Context, stage: str, step: str, argv: list, quiet_prefixes: tuple = ()) -> Path:
    log = ctx.path("logs", f"{stage}_{step}.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    tail: deque[str] = deque(maxlen=40)
    _echo(f"\n[{stage}/{step}] $ {' '.join(map(str, argv))}\n")
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(f"$ {' '.join(map(str, argv))}\n")
        try:
            proc = subprocess.Popen([str(a) for a in argv], cwd=ctx.work, env=_env(ctx), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
        except OSError as exc:
            raise StageError(f"[{stage}/{step}] could not start process: {exc}") from exc
        try:
            for line in proc.stdout:
                fh.write(line)
                tail.append(line.rstrip("\n"))
                if not any(line.lstrip().startswith(p) for p in quiet_prefixes):
                    _echo(line)
            code = proc.wait()
        except BaseException:
            proc.kill()
            proc.wait()
            fh.write("\n# interrupted; child process killed\n")
            raise
        fh.write(f"\n# exit code {code} after {time.time() - t0:.0f}s\n")
    if code != 0:
        raise StageError(f"[{stage}/{step}] FAILED with exit code {code} after {time.time() - t0:.0f}s.\n"
                         f"Full log: {log}\nLast lines:\n" + "\n".join(tail))
    print(f"[{stage}/{step}] ok ({time.time() - t0:.0f}s)", flush=True)
    return log


# --------------------------------------------------------------------------- setup

def install_dependencies(ctx: Context) -> None:
    run_step(ctx, "setup", "pip_install", [sys.executable, "-m", "pip", "install", "--use-pep517",
                                            "-r", str(ctx.work / "requirements-colab.txt")])


def check_environment(ctx: Context, require_gpu: bool = True) -> dict:
    info_file = ctx.path("environment.json")
    info_file.parent.mkdir(parents=True, exist_ok=True)
    probe = (
        "import importlib, json, platform, sys\n"
        f"mods = {list(REQUIRED_IMPORTS)!r}\nproject = {list(PROJECT_IMPORTS)!r}\n"
        "info = {'python': sys.version.split()[0], 'platform': platform.platform(), 'versions': {}, 'errors': {}}\n"
        "for m in mods + project:\n"
        "    try:\n"
        "        mod = importlib.import_module(m)\n"
        "        info['versions'][m] = getattr(mod, '__version__', 'ok')\n"
        "    except Exception as e:\n"
        "        info['errors'][m] = f'{type(e).__name__}: {e}'\n"
        "try:\n"
        "    import pip; info['versions']['pip'] = pip.__version__\n"
        "except ImportError:\n"
        "    info['versions']['pip'] = None  # only needed for installation, not at runtime\n"
        "try:\n"
        "    import torch; info['cuda'] = torch.cuda.is_available(); info['gpu'] = torch.cuda.get_device_name(0) if info['cuda'] else None\n"
        "except Exception:\n"
        "    info['cuda'] = False\n"
        f"open({str(info_file)!r}, 'w').write(json.dumps(info, indent=2))\n"
        "print(json.dumps(info, indent=2))\n"
        "sys.exit(1 if info['errors'] else 0)\n"
    )
    try:
        run_step(ctx, "setup", "check_environment", [sys.executable, "-c", probe])
    except StageError as exc:
        raise StageError(f"{exc}\n\nOne or more required imports failed; fix the environment first.") from exc
    info = json.loads(info_file.read_text())
    if require_gpu and not info.get("cuda"):
        raise StageError("[setup/check_environment] CUDA is not available. Runtime > Change runtime type > GPU.")
    return info


def run_tests(ctx: Context) -> None:
    run_step(ctx, "setup", "pytest", [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", "tests"])


def verify_bundle(ctx: Context) -> dict:
    info_path = ctx.work / "BUNDLE_INFO.json"
    if not info_path.exists():
        raise StageError(f"{info_path} missing: the bundle on Drive is outdated. Upload the new bundle.")
    info = json.loads(info_path.read_text())
    if info.get("bundle_version") != ctx.spec.bundle_version:
        raise StageError(f"Bundle version {info.get('bundle_version')!r} != expected {ctx.spec.bundle_version!r}: "
                         "replace the bundle on Drive with the rebuilt one.")
    bad = [rel for rel, digest in info["files"].items() if _sha256(ctx.work / rel) != digest]
    if bad:
        raise StageError(f"Bundle files corrupted or modified after packaging: {bad[:10]}")
    print(f"bundle {ctx.spec.bundle_version} verified: {len(info['files'])} files match their recorded sha256")
    return info


# --------------------------------------------------------------------------- validation

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_counts(ctx: Context) -> dict[str, int]:
    manifest = json.loads((ctx.eval_dir / "manifest.json").read_text())
    return {name: meta["n_docs"] for name, meta in manifest["sets"].items()}


def validate_predictions(ctx: Context, run: str) -> dict:
    expected = _expected_counts(ctx)
    found = {}
    for name in ctx.sets:
        path = ctx.path("predictions", run, f"{name}.jsonl")
        if not path.exists():
            raise StageError(f"[validate] missing predictions {path}")
        ids, with_tokens = [], 0
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                ids.append(row["doc_id"])
                with_tokens += "tokens" in row
        if len(ids) != expected[name] or len(set(ids)) != len(ids):
            raise StageError(f"[validate] {path}: {len(ids)} rows ({len(set(ids))} unique), expected {expected[name]}")
        if with_tokens != len(ids):
            raise StageError(f"[validate] {path}: token probabilities missing for {len(ids) - with_tokens} docs")
        found[name] = len(ids)
    return found


def validate_metrics(ctx: Context, run: str) -> dict:
    path = ctx.path("reports", "runs", run, "metrics.json")
    if not path.exists():
        raise StageError(f"[validate] missing {path}")
    metrics = json.loads(path.read_text())
    summary = {}
    for name in ctx.sets:
        if name not in metrics.get("sets", {}):
            raise StageError(f"[validate] {path} has no results for {name}")
        micro = metrics["sets"][name]["entity"]["micro"]
        if not all(isinstance(micro[k], (int, float)) and math.isfinite(micro[k]) for k in ("precision", "recall", "f1")):
            raise StageError(f"[validate] {path}: non-numeric metrics for {name}")
        summary[name] = {"entity_f1": round(micro["f1"], 4), "false_allow_rate": metrics["sets"][name]["document"]["false_allow_rate"],
                         "false_block_rate": metrics["sets"][name]["document"]["false_block_rate"]}
    return summary


def validate_checkpoint(ctx: Context, path: Path, trained: bool) -> dict:
    if not path.is_dir():
        raise StageError(f"[validate] checkpoint directory not found: {path}")
    names = {p.name for p in path.iterdir()}
    weights = [p for p in path.iterdir() if p.suffix == ".safetensors" or p.name == "pytorch_model.bin"]
    if "config.json" not in names or not weights:
        raise StageError(f"[validate] {path} lacks config.json or weights (has {sorted(names)})")
    if not ({"tokenizer.json", "tokenizer_config.json"} & names):
        raise StageError(f"[validate] {path} has no tokenizer files (has {sorted(names)})")
    config = json.loads((path / "config.json").read_text())
    sys.path.insert(0, str(ctx.work / "src"))
    from confidentiality_detector.labels import validate_label_mapping

    try:
        validate_label_mapping(config["id2label"])
    except ValueError as exc:
        raise StageError(f"[validate] {path}: {exc}") from exc
    out = {"weights": {p.name: p.stat().st_size for p in weights}}
    if trained:
        summary_path = path / "training_summary.json"
        if not summary_path.exists():
            raise StageError(f"[validate] {summary_path} missing")
        summary = json.loads(summary_path.read_text())
        if summary.get("reload_ok") is not True:
            raise StageError(f"[validate] {path}: reloaded checkpoint did not reproduce its validation score")
        out.update({"best_checkpoint": summary["best_checkpoint"], "best_score": summary["best_score"],
                    "history": summary["history"], "data_versions": summary.get("data_versions")})
    return out


# --------------------------------------------------------------------------- stages

def _status_path(ctx: Context, stage: str) -> Path:
    return ctx.path("status", f"{stage}.json")


def stage_status(ctx: Context, stage: str) -> dict | None:
    path = _status_path(ctx, stage)
    return json.loads(path.read_text()) if path.exists() else None


def _write_status(ctx: Context, stage: str, payload: dict) -> None:
    path = _status_path(ctx, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stage": stage, "round": ctx.spec.name, "bundle_version": ctx.spec.bundle_version,
                                "smoke": ctx.smoke, "time": time.strftime("%Y-%m-%d %H:%M:%S"), **payload}, indent=2))


def _clean(paths) -> None:
    for p in paths:
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()


def _predict_and_evaluate(ctx: Context, stage: str, run: str, model_dir: Path) -> dict:
    py = sys.executable
    run_step(ctx, stage, "predict", [py, "scripts/predict.py", "--detector", "transformer", "--model-dir", model_dir,
                                     "--name", run, "--eval-dir", ctx.eval_dir, "--out-root", ctx.path("predictions"),
                                     "--batch-size", "64", "--sets", *ctx.sets])
    run_step(ctx, stage, "evaluate", [py, "scripts/evaluate.py", "--pred", run, "--pred-root", ctx.path("predictions"),
                                      "--eval-dir", ctx.eval_dir, "--out-root", ctx.path("reports", "runs"), "--sets", *ctx.sets])
    return {"predictions": validate_predictions(ctx, run), "metrics": validate_metrics(ctx, run)}


def run_stage(ctx: Context, key: str, force: bool = False) -> dict:
    spec = ctx.spec.stage(key)
    previous = stage_status(ctx, key)
    if previous and previous.get("status") == "ok" and previous.get("smoke") == ctx.smoke and not force:
        print(f"Stage {key} already completed at {previous['time']}; skipping (force=True to rerun).")
        return previous
    print(f"=== Stage {key}: {spec.title} ===")
    _clean([ctx.path("predictions", spec.run), ctx.path("reports", "runs", spec.run), _status_path(ctx, key)])
    _write_status(ctx, key, {"status": "running"})
    t0 = time.time()
    try:
        if spec.config is None:
            model_dir = ctx.models.get(spec.model)
            if model_dir is None:
                raise StageError(f"[{key}] no model registered under {spec.model!r} (Context.models)")
            checkpoint = validate_checkpoint(ctx, model_dir, trained=False)
            hashes = {p.name: _sha256(p) for p in model_dir.iterdir() if p.suffix == ".safetensors"}
            result = {"checkpoint": checkpoint, **_predict_and_evaluate(ctx, key, spec.run, model_dir)}
            if {p.name: _sha256(p) for p in model_dir.iterdir() if p.suffix == ".safetensors"} != hashes:
                raise StageError(f"[{key}] the existing checkpoint's weights changed during the stage")
            result["checkpoint_sha256"] = hashes
        else:
            config = ctx.spec.smoke_config if ctx.smoke else spec.config
            save_root = ctx.path("checkpoints")
            _clean([ctx.train_dir / spec.run, save_root / spec.run])
            argv = [sys.executable, "scripts/train.py", "--config", config, "--run-name", spec.run,
                    "--eval-dir", ctx.eval_dir, "--work-dir", ctx.train_dir, "--save-dir", save_root]
            if ctx.smoke:
                argv += ["--limit-train", "200", "--limit-val", "50"]
            run_step(ctx, key, "train", argv, quiet_prefixes=("Loading weights",))
            model_dir = save_root / spec.run
            result = {"checkpoint": validate_checkpoint(ctx, model_dir, trained=True)}
            result.update(_predict_and_evaluate(ctx, key, spec.run, model_dir))
    except Exception as exc:
        _write_status(ctx, key, {"status": "failed", "error": str(exc)[:4000], "seconds": round(time.time() - t0)})
        raise
    _write_status(ctx, key, {"status": "ok", "seconds": round(time.time() - t0), "result": result})
    print(f"=== Stage {key} OK in {(time.time() - t0) / 60:.1f} min ===")
    print(json.dumps(result.get("metrics", {}), indent=1))
    return stage_status(ctx, key)


# --------------------------------------------------------------------------- packaging

def package(ctx: Context, allow_partial: bool = False) -> Path:
    keys = [s.key for s in ctx.spec.stages]
    statuses = {k: (stage_status(ctx, k) or {}).get("status", "not run") for k in keys}
    ok = [k for k in keys if statuses[k] == "ok"]
    missing = [k for k in keys if statuses[k] != "ok"]
    if not ok:
        raise StageError(f"no stage is ok ({statuses}); nothing valid to package")
    if missing and not allow_partial:
        raise StageError(f"Stages {missing} are not ok ({statuses}). Re-run them, or call package(ctx, "
                         "allow_partial=True) for an archive explicitly marked PARTIAL.")
    for k in ok:
        run = ctx.spec.stage(k).run
        validate_predictions(ctx, run)
        validate_metrics(ctx, run)

    members: dict[str, Path] = {}
    for k in ok:
        spec = ctx.spec.stage(k)
        for p in sorted(ctx.path("predictions", spec.run).glob("*")):
            members[f"predictions/{spec.run}/{p.name}"] = p
        members[f"reports/runs/{spec.run}/metrics.json"] = ctx.path("reports", "runs", spec.run, "metrics.json")
        if spec.config:
            for f in ("config.json", "history.json", "training_summary.json"):
                p = ctx.path("checkpoints", spec.run, f)
                if p.exists():
                    members[f"checkpoint_meta/{spec.run}/{f}"] = p
    for p in sorted(ctx.path("logs").glob("*.log")) + sorted(ctx.path("status").glob("*.json")):
        members[f"{p.parent.name}/{p.name}"] = p
    for extra in (ctx.path("environment.json"), ctx.work / "BUNDLE_INFO.json"):
        if extra.exists():
            members[extra.name] = extra

    complete = not missing
    manifest = {"round": ctx.spec.name, "bundle_version": ctx.spec.bundle_version, "smoke": ctx.smoke, "complete": complete,
                "stages": statuses, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                "files": {arc: {"sha256": _sha256(p), "bytes": p.stat().st_size} for arc, p in members.items()}}
    base = f"{ctx.spec.name}_results"
    archive = ctx.path(f"{base}.zip" if complete else f"{base}_PARTIAL.zip")
    _clean([ctx.path(f"{base}.zip"), ctx.path(f"{base}_PARTIAL.zip")])
    tmp = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, p in members.items():
            zf.write(p, arc)
        zf.writestr("RESULTS_MANIFEST.json", json.dumps(manifest, indent=2))
    with zipfile.ZipFile(tmp) as zf:
        if zf.testzip() is not None:
            raise StageError(f"archive {tmp} is corrupt")
        listed = {i.filename: i.file_size for i in zf.infolist()}
        wrong = [a for a, m in manifest["files"].items() if listed.get(a) != m["bytes"]]
        if wrong:
            raise StageError(f"archive is missing or truncated members: {wrong[:10]}")
    tmp.replace(archive)
    _echo(f"{'COMPLETE' if complete else 'PARTIAL (missing ' + ','.join(missing) + ')'} archive: {archive} "
          f"({archive.stat().st_size / 1e6:.1f} MB, {len(members)} files)\n")
    return archive
