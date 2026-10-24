"""Failure handling of the generic, spec-driven Colab runner (round 2 onward)."""

import json
import sys
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import colab_round2  # noqa: E402,F401  (the real spec must import cleanly)
import colab_runner as cr  # noqa: E402

SETS = ("validation", "dev_v1")
SPEC = cr.RoundSpec(
    name="roundX", bundle_version="roundX-r1", eval_dir="data/eval_x",
    stages=(cr.StageSpec("R0", "base", "baseline", model="base"), cr.StageSpec("R1", "exp", "experiment", config="cfg.json")),
    smoke_config="cfg.json", smoke_sets=SETS)


@pytest.fixture
def ctx(tmp_path):
    work = tmp_path / "work"
    (work / "data/eval_x").mkdir(parents=True)
    (work / "data/eval_x/manifest.json").write_text(json.dumps({"sets": {s: {"n_docs": 2} for s in SETS}}))
    return cr.Context(spec=SPEC, work=work, out=tmp_path / "out", models={"base": tmp_path / "ckpt"}, smoke=True)


def write_run(ctx, run, n_docs=2):
    for name in SETS:
        p = ctx.path("predictions", run, f"{name}.jsonl")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps({"doc_id": f"d{i}", "spans": [], "tokens": []}) + "\n" for i in range(n_docs)))
    m = {"sets": {s: {"entity": {"micro": {"precision": 1.0, "recall": 1.0, "f1": 1.0}},
                      "document": {"false_allow_rate": 0.0, "false_block_rate": 0.0}} for s in SETS}}
    p = ctx.path("reports", "runs", run, "metrics.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m))


def test_round2_spec_is_one_factor_chain():
    keys = [s.key for s in colab_round2.ROUND2.stages]
    assert keys == ["R0", "R1", "R2", "R3", "R4"] and colab_round2.ROUND2.eval_dir == "data/eval_v3"
    for s in colab_round2.ROUND2.stages[1:]:
        assert (ROOT / s.config).exists(), s.config
        assert json.loads((ROOT / s.config).read_text())["name"] == s.run


def test_run_step_propagates_failure(ctx):
    with pytest.raises(cr.StageError, match=r"\[R1/train\] FAILED with exit code 4"):
        cr.run_step(ctx, "R1", "train", [sys.executable, "-c", "import sys; print('x'); sys.exit(4)"])
    assert "exit code 4" in ctx.path("logs", "R1_train.log").read_text()


def test_interrupt_kills_child(ctx, monkeypatch):
    monkeypatch.setattr(cr, "_echo", lambda line: (_ for _ in ()).throw(KeyboardInterrupt))
    t0 = time.time()
    with pytest.raises(KeyboardInterrupt):
        cr.run_step(ctx, "R1", "train", [sys.executable, "-c", "print('go', flush=True); import time; time.sleep(60)"])
    assert time.time() - t0 < 30


def test_predict_only_stage_requires_registered_model(ctx):
    ctx.models.clear()
    with pytest.raises(cr.StageError, match="no model registered"):
        cr.run_stage(ctx, "R0")
    assert cr.stage_status(ctx, "R0")["status"] == "failed"


def test_package_rules(ctx):
    with pytest.raises(cr.StageError, match="nothing valid"):
        cr.package(ctx)
    write_run(ctx, "base")
    cr._write_status(ctx, "R0", {"status": "ok"})
    with pytest.raises(cr.StageError, match=r"Stages \['R1'\] are not ok"):
        cr.package(ctx)
    assert cr.package(ctx, allow_partial=True).name == "roundX_results_PARTIAL.zip"
    cr._write_status(ctx, "R1", {"status": "ok"})  # status claims success, artifacts missing
    with pytest.raises(cr.StageError, match="missing predictions"):
        cr.package(ctx)
    write_run(ctx, "exp")
    archive = cr.package(ctx)
    assert archive.name == "roundX_results.zip"
    with zipfile.ZipFile(archive) as zf:
        assert json.loads(zf.read("RESULTS_MANIFEST.json"))["complete"] is True


def test_stale_bundle_detected(ctx):
    with pytest.raises(cr.StageError, match="outdated"):
        cr.verify_bundle(ctx)
    (ctx.work / "BUNDLE_INFO.json").write_text(json.dumps({"bundle_version": "round1-r2", "files": {}}))
    with pytest.raises(cr.StageError, match="replace the bundle"):
        cr.verify_bundle(ctx)
