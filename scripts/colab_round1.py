"""Fail-fast orchestration of experiment round 1 (driven by notebooks/colab/05_round1_experiments.ipynb).

Every external step runs as a subprocess whose exit code is checked explicitly (no shell
pipelines, so `tee`/`grep` can never mask a failure). Full output is streamed to the
console and to <out>/logs/<stage>_<step>.log. A stage writes <out>/status/<stage>.json
with status "ok" only after its artifacts pass validation; any failure raises StageError,
which stops a Colab "Run all". Packaging refuses to label an archive complete unless every
required stage is verifiably ok, and re-reads the archive after writing it.
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

BUNDLE_VERSION = "round1-r2"
EVAL_SETS = (
    "validation", "test", "test_unseen_context", "test_unseen_value", "test_novel_template",
    "test_familiar_template", "test_format_shift", "test_long", "challenge_v1",
)
STAGES = {
    "A": {"run": "mbert_original", "config": None, "title": "existing checkpoint-4352: metric reproduction + predictions"},
    "B": {"run": "e1_mbert_v2", "config": "configs/experiments/e1_mbert_v2.json", "title": "E1: v2 label policy"},
    "C": {"run": "e2_mbert_v2_fmtA", "config": "configs/experiments/e2_mbert_v2_fmtA.json", "title": "E2: E1 + format-A augmentation"},
}
REQUIRED_IMPORTS = ("torch", "transformers", "numpy", "sklearn", "safetensors", "seqeval", "phonenumbers", "pytest")
PROJECT_IMPORTS = (
    "confidentiality_detector.labels", "confidentiality_detector.alignment", "confidentiality_detector.metrics",
    "confidentiality_detector.decoding", "confidentiality_detector.perturb", "confidentiality_detector.challenge",
    "confidentiality_detector.detectors.transformer", "confidentiality_detector.detectors.hybrid",
    "confidentiality_detector.detectors.rules",
)


class StageError(RuntimeError):
    """A pipeline step failed; the message names the stage, step, exit code and log file."""


@dataclass
class Context:
    work: Path                       # extracted bundle (code + data)
    out: Path                        # persistent output dir (Google Drive)
    original_ckpt: Path              # existing checkpoint, read-only
    train_dir: Path = Path("/content/runs")
    smoke: bool = False              # local pipeline verification only: tiny model, few docs
    smoke_config: str = "configs/experiments/smoke_tiny.json"
    smoke_sets: tuple = ("validation", "challenge_v1", "test_long")
    extra_env: dict = field(default_factory=dict)

    def __post_init__(self):
        self.work, self.out, self.original_ckpt, self.train_dir = map(Path, (self.work, self.out, self.original_ckpt, self.train_dir))

    @property
    def sets(self) -> tuple:
        return self.smoke_sets if self.smoke else EVAL_SETS

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
    """Console echo that cannot fail on characters the console encoding lacks (the log keeps them)."""
    try:
        print(line, end="", flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc), end="", flush=True)


def run_step(ctx: Context, stage: str, step: str, argv: list[str], quiet_prefixes: tuple = ()) -> Path:
    """Run argv, stream its output to console + log, and raise StageError on a non-zero exit."""
    log = ctx.path("logs", f"{stage}_{step}.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    tail: deque[str] = deque(maxlen=40)
    print(f"\n[{stage}/{step}] $ {' '.join(map(str, argv))}", flush=True)
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
        except BaseException:  # includes KeyboardInterrupt (Colab "interrupt"): never leave a GPU job running
            proc.kill()
            proc.wait()
            fh.write("\n# interrupted; child process killed\n")
            raise
        fh.write(f"\n# exit code {code} after {time.time() - t0:.0f}s\n")
    if code != 0:
        raise StageError(
            f"[{stage}/{step}] FAILED with exit code {code} after {time.time() - t0:.0f}s.\n"
            f"Full log: {log}\nLast lines:\n" + "\n".join(tail))
    print(f"[{stage}/{step}] ok ({time.time() - t0:.0f}s)", flush=True)
    return log


# --------------------------------------------------------------------------- setup

def install_dependencies(ctx: Context) -> None:
    run_step(ctx, "setup", "pip_install", [sys.executable, "-m", "pip", "install", "--use-pep517",
                                            "-r", str(ctx.work / "requirements-colab.txt")])


def check_environment(ctx: Context, require_gpu: bool = True) -> dict:
    """Import every dependency and project module in a FRESH interpreter (what the scripts see)."""
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
        "import pip; info['versions']['pip'] = pip.__version__\n"
        "try:\n"
        "    import torch; info['cuda'] = torch.cuda.is_available(); info['gpu'] = torch.cuda.get_device_name(0) if info['cuda'] else None\n"
        "except Exception as e:\n"
        "    info['cuda'] = False\n"
        f"open({str(info_file)!r}, 'w').write(json.dumps(info, indent=2))\n"
        "print(json.dumps(info, indent=2))\n"
        "sys.exit(1 if info['errors'] else 0)\n"
    )
    try:
        run_step(ctx, "setup", "check_environment", [sys.executable, "-c", probe])
    except StageError as exc:
        raise StageError(f"{exc}\n\nOne or more required imports failed (see 'errors' above). "
                         "Do not continue: fix the environment first.") from exc
    info = json.loads(info_file.read_text())
    if require_gpu and not info.get("cuda"):
        raise StageError("[setup/check_environment] CUDA is not available. Runtime > Change runtime type > GPU.")
    return info


def run_tests(ctx: Context) -> None:
    run_step(ctx, "setup", "pytest", [sys.executable, "-m", "pytest", "-q", "-rs", "tests"])


def verify_bundle(ctx: Context) -> dict:
    info_path = ctx.work / "BUNDLE_INFO.json"
    if not info_path.exists():
        raise StageError(f"{info_path} missing: the bundle on Drive is outdated. Upload the new dist/colab_bundle.zip.")
    info = json.loads(info_path.read_text())
    if info.get("bundle_version") != BUNDLE_VERSION:
        raise StageError(f"Bundle version {info.get('bundle_version')!r} != expected {BUNDLE_VERSION!r}: "
                         "replace colab_bundle.zip on Drive with the rebuilt one.")
    bad = [rel for rel, sha in info["files"].items() if _sha256(ctx.work / rel) != sha]
    if bad:
        raise StageError(f"Bundle files corrupted or modified after packaging: {bad[:10]}")
    print(f"bundle {BUNDLE_VERSION} verified: {len(info['files'])} files match their recorded sha256")
    return info


# --------------------------------------------------------------------------- validation

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_counts(ctx: Context) -> dict[str, int]:
    manifest = json.loads((ctx.work / "data/eval/manifest.json").read_text())
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
        summary[name] = {"entity_f1": round(micro["f1"], 4),
                         "false_allow_rate": metrics["sets"][name]["document"]["false_allow_rate"]}
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
            raise StageError(f"[validate] {path}: reloaded checkpoint did not reproduce its validation score "
                             f"(reload_ok={summary.get('reload_ok')})")
        out.update({"best_checkpoint": summary["best_checkpoint"], "best_score": summary["best_score"],
                    "history": summary["history"]})
    return out


def validate_reproduction(path: Path) -> dict:
    if not path.exists():
        raise StageError(f"[validate] missing {path}")
    rows = json.loads(path.read_text())["rows"]
    for key in ("A_seqeval_ignored_as_O", "B_seqeval_ignored_dropped", "C_charspan_v1_gold", "D_charspan_v2_gold"):
        if key not in rows or not all(0.0 <= rows[key][m] <= 1.0 for m in ("precision", "recall", "f1")):
            raise StageError(f"[validate] {path}: row {key} missing or invalid")
    return rows


# --------------------------------------------------------------------------- stages

def _status_path(ctx: Context, stage: str) -> Path:
    return ctx.path("status", f"{stage}.json")


def stage_status(ctx: Context, stage: str) -> dict | None:
    path = _status_path(ctx, stage)
    return json.loads(path.read_text()) if path.exists() else None


def _write_status(ctx: Context, stage: str, payload: dict) -> None:
    path = _status_path(ctx, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stage": stage, "bundle_version": BUNDLE_VERSION, "smoke": ctx.smoke,
                                "time": time.strftime("%Y-%m-%d %H:%M:%S"), **payload}, indent=2))


def _clean(paths) -> None:
    for p in paths:
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()


def _predict_and_evaluate(ctx: Context, stage: str, run: str, model_dir: Path) -> dict:
    py = sys.executable
    run_step(ctx, stage, "predict", [py, "scripts/predict.py", "--detector", "transformer", "--model-dir", model_dir,
                                     "--name", run, "--out-root", ctx.path("predictions"), "--batch-size", "64",
                                     "--sets", *ctx.sets])
    run_step(ctx, stage, "evaluate", [py, "scripts/evaluate.py", "--pred", run, "--pred-root", ctx.path("predictions"),
                                      "--out-root", ctx.path("reports", "runs"), "--sets", *ctx.sets])
    return {"predictions": validate_predictions(ctx, run), "metrics": validate_metrics(ctx, run)}


def run_stage(ctx: Context, stage: str, force: bool = False) -> dict:
    """Run stage A, B or C. A stage already marked ok is skipped (resume) unless force=True."""
    if stage not in STAGES:
        raise ValueError(stage)
    spec = STAGES[stage]
    previous = stage_status(ctx, stage)
    if previous and previous.get("status") == "ok" and previous.get("smoke") == ctx.smoke and not force:
        print(f"Stage {stage} already completed at {previous['time']}; skipping (force=True to rerun).")
        return previous
    run = spec["run"]
    print(f"=== Stage {stage}: {spec['title']} ===")
    _clean([ctx.path("predictions", run), ctx.path("reports", "runs", run), _status_path(ctx, stage)])
    _write_status(ctx, stage, {"status": "running"})
    t0 = time.time()
    py = sys.executable
    try:
        if spec["config"] is None:
            ckpt_before = validate_checkpoint(ctx, ctx.original_ckpt, trained=False)
            weight_hashes = {p.name: _sha256(p) for p in ctx.original_ckpt.iterdir() if p.suffix == ".safetensors"}
            repro = ctx.path("reports", "runs", "original_metric_reproduction.json")
            _clean([repro])
            run_step(ctx, stage, "reproduce_metric", [py, "scripts/reproduce_original_metric.py",
                                                      "--model-dir", ctx.original_ckpt, "--out", repro])
            result = {"checkpoint": ckpt_before, "reproduction": validate_reproduction(repro)}
            result.update(_predict_and_evaluate(ctx, stage, run, ctx.original_ckpt))
            if {p.name: _sha256(p) for p in ctx.original_ckpt.iterdir() if p.suffix == ".safetensors"} != weight_hashes:
                raise StageError("[A] the original checkpoint's weights changed during the stage")
            result["checkpoint_sha256"] = weight_hashes
        else:
            config = ctx.smoke_config if ctx.smoke else spec["config"]
            save_root = ctx.path("checkpoints")
            _clean([ctx.train_dir / run, save_root / run])
            argv = [py, "scripts/train.py", "--config", config, "--run-name", run,
                    "--work-dir", ctx.train_dir, "--save-dir", save_root]
            if ctx.smoke:
                argv += ["--limit-train", "200", "--limit-val", "50"]
            run_step(ctx, stage, "train", argv, quiet_prefixes=("Loading weights",))
            model_dir = save_root / run
            result = {"checkpoint": validate_checkpoint(ctx, model_dir, trained=True)}
            result.update(_predict_and_evaluate(ctx, stage, run, model_dir))
    except Exception as exc:
        _write_status(ctx, stage, {"status": "failed", "error": str(exc)[:4000], "seconds": round(time.time() - t0)})
        raise
    _write_status(ctx, stage, {"status": "ok", "seconds": round(time.time() - t0), "result": result})
    print(f"=== Stage {stage} OK in {(time.time() - t0) / 60:.1f} min ===")
    print(json.dumps(result.get("metrics", {}), indent=1))
    return stage_status(ctx, stage)


# --------------------------------------------------------------------------- packaging

def package(ctx: Context, required: tuple = ("A", "B", "C"), allow_partial: bool = False) -> Path:
    """Zip predictions/metrics/logs/status (no weights). Refuses to produce a 'complete' archive
    unless every required stage is ok and its artifacts re-validate."""
    statuses = {s: (stage_status(ctx, s) or {}).get("status", "not run") for s in STAGES}
    ok = [s for s in STAGES if statuses[s] == "ok"]
    missing = [s for s in required if statuses[s] != "ok"]
    if "A" not in ok:
        raise StageError(f"Stage A is not ok ({statuses}); nothing valid to package.")
    if missing and not allow_partial:
        raise StageError(f"Stages {missing} are not ok ({statuses}). Re-run them, or call package(..., "
                         "allow_partial=True) to create an archive explicitly marked PARTIAL.")
    for s in ok:  # re-validate: never trust a status file alone
        run = STAGES[s]["run"]
        validate_predictions(ctx, run)
        validate_metrics(ctx, run)
    validate_reproduction(ctx.path("reports", "runs", "original_metric_reproduction.json"))

    members: dict[str, Path] = {}
    for s in ok:
        run = STAGES[s]["run"]
        for p in sorted(ctx.path("predictions", run).glob("*")):
            members[f"predictions/{run}/{p.name}"] = p
        members[f"reports/runs/{run}/metrics.json"] = ctx.path("reports", "runs", run, "metrics.json")
        if STAGES[s]["config"]:
            for f in ("config.json", "history.json", "training_summary.json"):
                p = ctx.path("checkpoints", run, f)
                if p.exists():
                    members[f"checkpoint_meta/{run}/{f}"] = p
    members["reports/runs/original_metric_reproduction.json"] = ctx.path("reports", "runs", "original_metric_reproduction.json")
    for p in sorted(ctx.path("logs").glob("*.log")) + sorted(ctx.path("status").glob("*.json")):
        members[f"{p.parent.name}/{p.name}"] = p
    if ctx.path("environment.json").exists():
        members["environment.json"] = ctx.path("environment.json")
    if (ctx.work / "BUNDLE_INFO.json").exists():
        members["BUNDLE_INFO.json"] = ctx.work / "BUNDLE_INFO.json"

    complete = not missing
    manifest = {"bundle_version": BUNDLE_VERSION, "smoke": ctx.smoke, "complete": complete, "stages": statuses,
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                "files": {arc: {"sha256": _sha256(p), "bytes": p.stat().st_size} for arc, p in members.items()}}
    name = "round1_results.zip" if complete else "round1_results_PARTIAL.zip"
    archive = ctx.path(name)
    _clean([ctx.path("round1_results.zip"), ctx.path("round1_results_PARTIAL.zip")])
    tmp = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, p in members.items():
            zf.write(p, arc)
        zf.writestr("RESULTS_MANIFEST.json", json.dumps(manifest, indent=2))
    with zipfile.ZipFile(tmp) as zf:  # verify what was actually written
        if zf.testzip() is not None:
            raise StageError(f"archive {tmp} is corrupt")
        listed = {i.filename: i.file_size for i in zf.infolist()}
        wrong = [a for a, m in manifest["files"].items() if listed.get(a) != m["bytes"]]
        if wrong:
            raise StageError(f"archive is missing or truncated members: {wrong[:10]}")
    tmp.replace(archive)
    print(f"{'COMPLETE' if complete else 'PARTIAL (missing ' + ','.join(missing) + ')'} archive: {archive} "
          f"({archive.stat().st_size / 1e6:.1f} MB, {len(members)} files)")
    return archive
