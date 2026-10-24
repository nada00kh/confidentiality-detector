"""Import isolation: model training/evaluation must not depend on rule/Presidio-only packages."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_blocked(code: str, blocked=("phonenumbers", "presidio_analyzer")) -> subprocess.CompletedProcess:
    prelude = "import sys\n" + "".join(f"sys.modules[{m!r}] = None\n" for m in blocked)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run([sys.executable, "-c", prelude + code], cwd=ROOT, env=env, capture_output=True, text=True)


def test_transformer_and_hybrid_do_not_need_phonenumbers():
    res = _run_blocked("import confidentiality_detector.detectors.transformer\n"
                       "import confidentiality_detector.detectors.hybrid\n"
                       "from confidentiality_detector.detectors import merge\n")
    assert res.returncode == 0, res.stderr


def test_colab_entry_point_scripts_import_without_phonenumbers():
    for script in ("train", "evaluate", "reproduce_original_metric", "predict"):
        res = _run_blocked(f"import runpy, sys\nsys.argv = ['{script}.py', '--help']\n"
                           f"runpy.run_path('scripts/{script}.py', run_name='__main__')\n")
        assert res.returncode == 0, f"{script}: {res.stderr[-2000:]}"


def test_rules_still_fail_loudly_without_phonenumbers():
    res = _run_blocked("import confidentiality_detector.detectors.rules\n")
    assert res.returncode != 0 and "phonenumbers" in res.stderr
