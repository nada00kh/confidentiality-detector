# Colab round 1: failure analysis and repair (bundle `round1-r2`)

The first round-1 attempt on Colab produced **no valid results**. Its `MyDrive/confidentiality_detector/round1/` folder and the 182-byte `round1_results.zip` in it are excluded from all comparisons.

## Root cause (reproduced locally)

1. **`pip install -r requirements-colab.txt` failed because of `seqeval==1.2.2`, not `phonenumbers`.**
   * seqeval 1.2.2 exists only as an sdist, with no `pyproject.toml`, and its `setup.py` declares `setup_requires=["setuptools_scm"]` with `use_scm_version=True`.
   * pip < 26 with both `setuptools` and `wheel` installed (as on Colab) takes the legacy `python setup.py egg_info` path.
   * There, setuptools' deprecated `fetch_build_eggs` downloads the newest `setuptools_scm` (10.3.4) as an egg, without its new dependency `vcs_versioning`.
   * Result: `ModuleNotFoundError: No module named 'vcs_versioning'` → `egg_info did not run successfully` → `error: metadata-generation-failed`.
   * Reproduced in a fresh Python 3.13 venv with pip 24.2 + setuptools 84.2.1 + wheel 0.48.0, using the old requirements file (exit 1, same messages).
   * Your earlier notebook `04_mbert_finetuning.ipynb` had already needed `%pip install --use-pep517 seqeval` for this reason.
2. **`phonenumbers` was missing because pip aborts the whole install** when one requirement's metadata generation fails. phonenumbers is a pure wheel and was never the problem: after the failed command, `import phonenumbers` → `ModuleNotFoundError`, reproduced.
3. **Unnecessary coupling made every stage depend on phonenumbers.** `detectors/__init__.py` eagerly imported `rules` (which imports `phonenumbers`). So `detectors.transformer` (used by train, predict and the reproduction) and `detectors.hybrid` (used by evaluate) all failed, although none of them use the rule detector.
4. **`train.py` imported the detector inside `validate()`.** An import problem therefore surfaced only at the first per-epoch validation, after a full epoch of GPU time, and before that epoch was saved.
5. **The notebook did not stop on failure.**
   * IPython `!` commands do not raise on a non-zero exit.
   * `cmd | tee log | grep …` reports the exit status of `grep`, not of `cmd`.
   * The packaging cell suppressed `cp` errors (`2>/dev/null; …`) and zipped whatever existed, giving a 182-byte archive.

## Fixes (no change to model, data split, labels, hyper-parameters or evaluation)

| File | Change |
|---|---|
| `requirements-colab.txt` | Documents the cause. Pins `phonenumbers==9.0.40` (the version the local tests passed with) and adds `pytest`. `seqeval==1.2.2` is unchanged (same version as the original metric). |
| `scripts/colab_round1.py` (new) | Fail-fast orchestration (detailed below the table). |
| `notebooks/colab/05_round1_experiments.ipynb` | Rewritten as plain Python calls into `colab_round1`, with no `!` commands or pipes. Writes to the new `round1_rerun` folder. |
| `src/confidentiality_detector/detectors/__init__.py` | Lazy exports, so each detector imports only its own dependencies. |
| `scripts/train.py` | Detector import moved to module level (fails before training). Each epoch is saved **before** validation. New `--run-name` option. Optimisation, data and selection are unchanged. |
| `scripts/make_colab_bundle.py` | Writes `BUNDLE_INFO.json` (version + per-file SHA-256). Re-opens the zip and checks the required files. Extracts it, verifies hashes against sources and the eval manifest, runs an import probe and the full test suite from the extracted copy. |
| `pyproject.toml`, `uv.lock` | `phonenumbers` declared as a direct dependency (it is imported directly). |
| `tests/test_colab_round1.py`, `tests/test_imports.py` (new) | Exit-code propagation, interrupt kills the child, artifact validation, packaging refusals, stale-bundle detection, import isolation with `phonenumbers`/`presidio` blocked. |

What `scripts/colab_round1.py` does:
* Runs every step as a subprocess with an explicit exit-code check, streams output to the console and to `OUT/logs/<stage>_<step>.log`, and raises `StageError` naming the stage, step, exit code, log file and the last 40 lines.
* Kills the child process if the cell is interrupted.
* Installs dependencies with `pip install --use-pep517` and checks every dependency and project module in a fresh interpreter.
* Runs `pytest` before any GPU work.
* After each stage, validates its artifacts: row counts per eval set, token probabilities, finite metrics, label mapping, `reload_ok`, and the original weights hashed before and after.
* Records `status/<stage>.json` and skips completed stages on re-run.
* Packaging refuses unless A, B and C are ok **and** re-validate. It verifies the written archive, and an explicitly requested incomplete archive is named `round1_results_PARTIAL.zip`.

## Verification actually performed (local, Windows, CPU)

* `pytest`: **54 passed** in the project venv. From the extracted bundle: **51 passed, 2 skipped**; the two skips are the original-dataset equivalence tests, which need `data/processed/` (not bundled) and pass in the repo.
* **Colab-like fresh venv** (Python 3.13.0, pip 24.2, setuptools 84.2.1, wheel 0.48.0, transformers 5.20.1, torch 2.14.1 CPU):
  * old requirements command → fails exactly as on Colab;
  * new `install_dependencies` → `seqeval-1.2.2`, `phonenumbers-9.0.40`, `pytest` installed;
  * `check_environment` → all imports ok;
  * tests: 52 passed, 2 skipped.
* **Notebook path end to end in smoke mode** (same bundle, same `colab_round1` calls, tiny random model, 200 training docs, 3 eval sets): setup → A → B → C → resume-skip → complete archive (39 files) re-validated.
* **Negative runs:**
  * missing checkpoint → Stage A raises and records `failed`;
  * training subprocess crash → Stage B `FAILED with exit code 1`, recorded;
  * packaging then refused, and no archive was written.
* Notebook: valid nbformat-4 JSON, every code cell parses, no shell/magic commands.

## Not verifiable without Colab

* The CUDA/fp16 training path, T4 memory and run time (only CPU was exercised).
* Loading the real `checkpoint-4352` (`gamma/beta` LayerNorm names) inside this pipeline. `TransformerDetector` now **fails loudly** if any key is missing, instead of silently re-initialising.
* Linux/Colab specifics: actual pip version, Drive I/O speed (hashing the ~700 MB weights twice), and network access to the Hugging Face Hub for the mBERT tokenizer.
* Python versions other than 3.13.

The bundle has been tested on pip 24.2, 25.1 and 26.2.
