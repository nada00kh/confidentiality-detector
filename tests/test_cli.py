import importlib
import json
import os
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

from confidentiality_detector.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "confidentiality-detector"


def test_console_script_target_exists():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    module, _, func = scripts[SCRIPT].partition(":")
    assert callable(getattr(importlib.import_module(module), func))


def test_installed_console_script_matches_pyproject():
    try:
        dist = metadata.distribution("confidentiality-detector")
    except metadata.PackageNotFoundError:
        pytest.skip("package not installed (run `uv sync` or `pip install -e .`)")
    entry = {e.name: e.value for e in dist.entry_points if e.group == "console_scripts"}
    assert entry.get(SCRIPT) == "confidentiality_detector.__main__:main"


def test_python_m_entry_point_runs_outside_the_repository(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    run = subprocess.run([sys.executable, "-m", "confidentiality_detector", "--help"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0 and "--model-dir" in run.stdout


def test_cli_decisions_and_exit_codes(tiny_checkpoint, tmp_path, capsys):
    secret = tmp_path / "secret.txt"
    secret.write_text("Please forward the minutes to jane.doe@example.org before Friday.", encoding="utf-8")
    clean = tmp_path / "clean.txt"
    clean.write_text("Please summarise the attached meeting agenda in three bullet points.", encoding="utf-8")

    assert main(["--model-dir", str(tiny_checkpoint), "--file", str(secret), "--device", "cpu"]) == 10
    out = capsys.readouterr().out
    decision = json.loads(out)
    assert decision["decision"] == "BLOCK" and decision["categories"] == ["EMAIL"]
    assert "jane.doe" not in out  # the value never appears in the output

    assert main(["--model-dir", str(tiny_checkpoint), "--file", str(clean), "--device", "cpu"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "ALLOW"


def test_cli_configuration_errors_exit_2(tmp_path, capsys):
    assert main(["--model-dir", str(tmp_path / "missing")]) == 2
    assert "could not load detector" in capsys.readouterr().err
    assert main(["--model-dir", str(tmp_path), "--policy", str(tmp_path / "nope.json")]) == 2
    assert "policy file not found" in capsys.readouterr().err
