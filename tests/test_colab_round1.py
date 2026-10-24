"""Failure handling of the Colab orchestration (no GPU, no network needed)."""

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import colab_round1 as r1  # noqa: E402

SETS = ("validation", "challenge_v1")


@pytest.fixture
def ctx(tmp_path):
    work, out = tmp_path / "work", tmp_path / "out"
    (work / "data/eval").mkdir(parents=True)
    (work / "src").mkdir()
    manifest = {"sets": {name: {"n_docs": 2, "sha256": "x"} for name in SETS}}
    (work / "data/eval/manifest.json").write_text(json.dumps(manifest))
    return r1.Context(work=work, out=out, original_ckpt=tmp_path / "ckpt", smoke=True, smoke_sets=SETS)


def write_run(ctx, run, n_docs=2, tokens=True):
    for name in SETS:
        path = ctx.path("predictions", run, f"{name}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"doc_id": f"d{i}", "spans": [], **({"tokens": []} if tokens else {})} for i in range(n_docs)]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    metrics = {"sets": {name: {"entity": {"micro": {"precision": 1.0, "recall": 0.5, "f1": 0.66}},
                               "document": {"false_allow_rate": 0.1}} for name in SETS}}
    path = ctx.path("reports", "runs", run, "metrics.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics))


def mark_ok(ctx, stage):
    r1._write_status(ctx, stage, {"status": "ok"})


def write_reproduction(ctx):
    rows = {k: {"precision": 0.9, "recall": 0.9, "f1": 0.9} for k in
            ("A_seqeval_ignored_as_O", "B_seqeval_ignored_dropped", "C_charspan_v1_gold", "D_charspan_v2_gold")}
    path = ctx.path("reports", "runs", "original_metric_reproduction.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": rows}))


def test_run_step_propagates_nonzero_exit_and_keeps_log(ctx):
    with pytest.raises(r1.StageError, match=r"\[B/train\] FAILED with exit code 3") as err:
        r1.run_step(ctx, "B", "train", [sys.executable, "-c", "print('epoch 1'); import sys; sys.exit(3)"])
    log = ctx.path("logs", "B_train.log").read_text()
    assert "epoch 1" in log and "exit code 3" in log
    assert "epoch 1" in str(err.value)  # tail of the output is in the error message


def test_run_step_reports_import_errors_as_failures(ctx):
    with pytest.raises(r1.StageError, match="exit code 1"):
        r1.run_step(ctx, "A", "predict", [sys.executable, "-c", "import module_that_does_not_exist"])


def test_interrupt_kills_child_process(ctx, monkeypatch):
    import time

    def interrupt(line):
        raise KeyboardInterrupt

    monkeypatch.setattr(r1, "_echo", interrupt)
    t0 = time.time()
    with pytest.raises(KeyboardInterrupt):
        r1.run_step(ctx, "B", "train", [sys.executable, "-c", "print('start', flush=True); import time; time.sleep(60)"])
    assert time.time() - t0 < 30  # the 60 s child was killed, not waited for
    assert "child process killed" in ctx.path("logs", "B_train.log").read_text()


def test_run_step_success(ctx):
    log = r1.run_step(ctx, "A", "ok", [sys.executable, "-c", "print('fine')"])
    assert "fine" in log.read_text()


def test_validate_predictions_rejects_missing_and_short_files(ctx):
    with pytest.raises(r1.StageError, match="missing predictions"):
        r1.validate_predictions(ctx, "run")
    write_run(ctx, "run", n_docs=1)
    with pytest.raises(r1.StageError, match="expected 2"):
        r1.validate_predictions(ctx, "run")
    write_run(ctx, "run", tokens=False)
    with pytest.raises(r1.StageError, match="token probabilities missing"):
        r1.validate_predictions(ctx, "run")
    write_run(ctx, "run")
    assert r1.validate_predictions(ctx, "run") == {"validation": 2, "challenge_v1": 2}


def test_package_refuses_without_stage_A(ctx):
    with pytest.raises(r1.StageError, match="Stage A is not ok"):
        r1.package(ctx)
    assert not ctx.path("round1_results.zip").exists()


def test_package_refuses_incomplete_round_unless_partial_requested(ctx):
    write_run(ctx, "mbert_original")
    write_reproduction(ctx)
    mark_ok(ctx, "A")
    with pytest.raises(r1.StageError, match=r"Stages \['B', 'C'\] are not ok"):
        r1.package(ctx)
    archive = r1.package(ctx, allow_partial=True)
    assert archive.name == "round1_results_PARTIAL.zip"
    with zipfile.ZipFile(archive) as zf:
        manifest = json.loads(zf.read("RESULTS_MANIFEST.json"))
    assert manifest["complete"] is False and manifest["stages"]["B"] == "not run"


def test_package_never_trusts_status_alone(ctx):
    write_reproduction(ctx)
    for stage in ("A", "B", "C"):
        mark_ok(ctx, stage)  # statuses claim success, but no predictions exist
    with pytest.raises(r1.StageError, match="missing predictions"):
        r1.package(ctx)


def test_complete_archive_contains_every_artifact(ctx):
    write_reproduction(ctx)
    for stage, spec in r1.STAGES.items():
        write_run(ctx, spec["run"])
        mark_ok(ctx, stage)
    archive = r1.package(ctx)
    assert archive.name == "round1_results.zip"
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("RESULTS_MANIFEST.json"))
    assert manifest["complete"] is True
    assert {f"predictions/{s['run']}/validation.jsonl" for s in r1.STAGES.values()} <= names
    assert "reports/runs/original_metric_reproduction.json" in names


def test_failed_stage_is_recorded_and_raised(ctx, monkeypatch):
    def boom(*args, **kwargs):
        raise r1.StageError("[B/train] FAILED with exit code 1")

    monkeypatch.setattr(r1, "run_step", boom)
    (ctx.work / "configs/experiments").mkdir(parents=True)
    (ctx.work / ctx.smoke_config).write_text(json.dumps({"name": "smoke_tiny"}))
    with pytest.raises(r1.StageError):
        r1.run_stage(ctx, "B")
    assert r1.stage_status(ctx, "B")["status"] == "failed"


def test_verify_bundle_detects_stale_bundle(ctx):
    with pytest.raises(r1.StageError, match="outdated"):
        r1.verify_bundle(ctx)
    (ctx.work / "BUNDLE_INFO.json").write_text(json.dumps({"bundle_version": "round1-r1", "files": {}}))
    with pytest.raises(r1.StageError, match="replace colab_bundle.zip"):
        r1.verify_bundle(ctx)
