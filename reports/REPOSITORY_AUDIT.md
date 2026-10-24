# Repository audit (Phase 1)

**Date:** 2026-10-24. **Scope:** read-only inventory plus minimal, non-destructive packaging fixes. Nothing was deleted, moved or committed. Every "proposed action" below needs the product owner's approval before Phase 2.

Classes used throughout:
* **Active:** part of the authoritative pipeline, or needed to run or test it.
* **Historical:** original research and development work, preserved as evidence.
* **Reproducible:** generated output that a script rebuilds deterministically.
* **Redundant:** a verified duplicate, or an empty placeholder.
* **Uncertain:** needs the owner's input.

## 1. Key findings

1. **None of the engineering work since the first commits is under version control.** `src/confidentiality_detector/`, `scripts/`, `tests/`, `configs/`, `docs/`, the hand-written `data/dev` and `data/challenge` files, the split manifests and all reports are untracked: about 14.5 MB of text and small data. The only copy is this OneDrive folder. A recoverable checkpoint is the first prerequisite for Phase 2 (§8).
2. **The historical Colab results are deliberately git-ignored** (`results/round1`, 0.8 MB of metadata + 81 MB of predictions; `results/round2`, 145 MB). They are not reproducible without GPU retraining. They exist here, as the two archives in `Downloads/` and on Google Drive. Their hashes should be recorded in a committed file (§6).
3. **The authoritative data split is yours.** `notebooks/02_mbert_dataset_splitting.ipynb` produced train/validation/test = 34,802 / 4,350 / 4,349 after removing template overlap between splits. `data/splits/original/*.ids` freezes exactly those ids, and every Round 1 and Round 2 run used them.
4. **Your tokenisation and alignment were mechanically correct.** `tests/test_alignment.py` proves that the current `alignment.training_features`, under label policy v1, reproduces `data/processed/mbert_tokenized` (the output of notebook 03) exactly. What later proved wrong was the **label policy** (out-of-scope entities set to `-100`) and the **evaluation** (token-level seqeval on windows), not the alignment code.
5. **One remaining notebook belongs to the earlier Arabic direction (verified, not assumed).** `notebooks/02_scoped_data_EDA.ipynb`:
   * loads `mabahboh/sitr-arabic-pii`;
   * its outputs contain Arabic text;
   * its 11 categories (`national_id`, `iqama`, `api_key`, `access_token`, `national_address`, …) are the old scope.

   The other four notebooks use the English ai4privacy data. I have not changed it; its classification is your decision (§9).
6. **The CLI was broken, and is now fixed.**
   * `[tool.uv] package = false` meant uv never installed the package, so the documented `python -m confidentiality_detector` failed with "No module named confidentiality_detector".
   * `[project.scripts]` pointed to `confidentiality_detector:main`, which does not exist.
7. **Empty placeholders from the project template are still tracked:** `mbert_ner`, `evaluation/metrics.py`, `src/detectors/mbert_detector.py`, `src/training/bio_alignment.py` (all 0 bytes), `src/detectors/__init__.py` (a uv "Hello" stub), and the empty folder `state/`.
8. **Seven declared dependencies are never imported**, and several others serve only notebooks or the Presidio baseline (§5).

## 2. The authoritative pipeline

| Stage | Files |
|---|---|
| Source data | `data/raw/english_pii_43k.jsonl` (43,501 English ai4privacy records, sha256 `1a7aac12…`; downloaded from a Hugging Face Hub repository, revision `7c22e681…`; git-ignored) |
| Split | `data/splits/original/{train,validation,test}.ids` (frozen ids from your splitting notebook) |
| Scope and annotation policy | `src/confidentiality_detector/labels.py` (13 labels, policies v1/v2/v3, CVV evidence), `documents.py` |
| Evaluation sets | `scripts/build_eval_sets.py` → `data/eval` (Round 1, policy v2) and `data/eval_v3` (Round 2+, policy v3, frozen manifest `manifest_round2.json`) |
| Hand-written sets | `data/dev/dev_v1.txt`, `data/challenge/challenge_v1.txt` + two overlays (frozen; irreplaceable) |
| Round 2 training data | `scripts/build_synth_round2.py` + `src/confidentiality_detector/synth.py` → `data/synth/round2/` |
| Tokenisation, windows | `alignment.py`, `decoding.py` |
| Training | `scripts/train.py`, `configs/experiments/*.json`; GPU runs via `notebooks/colab/05_*`, `06_*`, `scripts/colab_*.py`, `scripts/make_colab_bundle.py` |
| Inference | `pipeline.py` (`ConfidentialityDetector`), `detectors/transformer.py`, `detectors/rules.py` (rules v3), `detectors/hybrid.py`, `postprocess.py`, `policy.py`, `__main__.py`, `configs/inference/policy.json` |
| Evaluation | `metrics.py`, `runio.py`, `scripts/predict.py`, `evaluate.py`, `evaluate_system.py`, `analyze_round2.py`, `verify_round2.py`, `analyze_long_docs.py`, `operating_points.py`, `calibration.py` |
| Pre-freeze studies | `scripts/verify_checkpoint.py`, `window_study.py`, `ipv4_gate_study.py` |
| Independent benchmark | `scripts/challenge_v2.py`, `docs/CHALLENGE_V2_SPEC.md`, `docs/CASE_FORMAT.md` |
| Selected model | `r2_e3b_positive` (Drive `confidentiality_detector/round2/checkpoints/r2_e3b_positive`; not in the repository) |

## 3. Inventory

| Path | Contents | Used by | Regenerable? | Irreplaceable? | Backup | Class | Proposed action (Phase 2) |
|---|---|---|---|---|---|---|---|
| `src/confidentiality_detector/` | the package | everything | — | yes (code) | none (untracked) | Active | keep; commit |
| `scripts/` (25 scripts) | pipeline, analysis, Colab, studies | docs, tests, Colab | — | yes (code) | none | Active (see §3.1) | keep flat; add `scripts/README.md` index |
| `tests/` (14 files, 142 tests) | unit and integration tests | CI/local | — | yes | none | Active | keep; commit |
| `configs/experiments/` | E1, E2, R1–R4, smoke configs | train.py, Colab | — | yes | none | Active | keep |
| `configs/inference/policy.json` | security policy, modes, windows, postprocessing | pipeline, CLI, freeze | — | yes | none | Active | keep (§7 on splitting it) |
| `docs/` (8 files) | policy, annotation, data, methodology, architecture, case format, challenge spec, risks | readers | — | yes | none | Active | keep; `POLICY.md` becomes the single scope authority |
| `reports/*.md` | investigation, round reports, plan, this audit | readers | — | yes | none | Active / Historical | keep; add the final consolidated report later |
| `reports/*.json` | evidence behind the reports (integrity, selection, system eval, long docs, calibration, operating points) | reports | yes, from results + scripts | no | none | Reproducible (small) | keep and commit as evidence (≈1.4 MB) |
| `reports/runs/` (ignored), `reports/runs_v3/` | per-run metrics from `evaluate.py` | analysis | yes | no | — | Reproducible | keep `runs_v3`; leave `runs` ignored |
| `data/raw/english_pii_43k.jsonl` | the source data (with your `mbert_*` preprocessing columns) | everything | only by re-download (HF Hub) | **yes, root of all results** | HF Hub repository (please confirm its name) | Active | keep, git-ignored; record its sha256 and origin in a data README |
| `data/raw/.cache/` | HF download metadata | — | yes | no | — | Reproducible | keep (tiny; documents provenance) |
| `data/splits/original/*.ids` | frozen split | build_eval_sets, train.py | from `data/processed/mbert_splits` | effectively yes | none | Active | **commit** (0.35 MB) |
| `data/processed/mbert_splits/` | your saved splits (arrow) + 6 `cache-*.arrow` files | split export fallback; `test_alignment` | by re-running notebook 02_mbert_dataset_splitting | historical artefact | `mbert_splits.zip` (identical core files) | Historical | keep (git-ignored); cache files can go |
| `data/processed/mbert_tokenized/` | your tokenised windows (policy v1) | `test_alignment` equivalence proof | by re-running notebook 03 | historical artefact | `mbert_tokenized.zip` (identical data; only `state.json` fingerprints differ) | Historical | keep (proves the alignment equivalence) |
| `data/processed/*.zip` | the copies uploaded to Drive for notebook 04 | notebook 04 (Colab) | yes (zip of the folders) | no | the folders | Redundant locally | propose deleting the local zips (−25 MB), or keep as "what Colab trained on" — your call |
| `data/eval/` | Round 1 evaluation sets (policy v2) | Round 1 provenance | yes, `build_eval_sets.py --policy v2` (deterministic) | no | — | Reproducible / Historical | keep (jsonl ignored; manifest committed) |
| `data/eval_v3/` | Round 2+ evaluation sets, `manifest_round2.json` | all Round 2 evidence | yes (verified byte-identical rebuild) | frozen record | none | Active | commit (8 MB), or commit the manifests only and rebuild — your call |
| `data/dev/`, `data/challenge/` | hand-written frozen sets, overlays, sha256 files | evaluation | **no** | **yes** | none | Active | **commit** |
| `data/synth/round2/` | Round 2 generated training and held-out data + manifest | train.py (sha-checked), eval | yes (seeded generator) | no | none | Active | commit (2.7 MB; pinned by sha in training summaries) |
| `results/round1/`, `results/round2/` | Colab result archives, extracted | all Round 1/2 evidence | **no** (GPU retraining) | **yes** | `Downloads/round*_results.zip`, Drive | Historical | keep out of git; commit a manifest of archive hashes |
| `results/round2_derived/` | predictions retargeted to `challenge_v1_final` | system eval | yes | no | — | Reproducible | keep |
| `predictions/` (ignored) | Round 1 local predictions: Presidio, rules v1, rules v2 | `analyze_round1.py` | rules v1/v2 only from old code; Presidio yes | historical | — | Historical | keep |
| `predictions_v3/` (ignored) | rules v2/v3 and E2 (retargeted) on the v3 sets | `analyze_round2`, `evaluate_system` | yes | no | — | Reproducible | keep |
| `dist/colab_bundle_round1-r2.zip`, `dist/colab_bundle_round2.zip` | the exact uploaded bundles | provenance of the results | yes, with the then code | proof of what ran | — | Historical | keep (ignored) |
| `dist/colab_bundle.zip` | **byte-identical** to `colab_bundle_round1-r2.zip` (sha256 `1499e7d4…`) | nothing | — | no | the other file | Redundant | propose delete (ignored file) |
| `notebooks/02_2scoped_data_EDA.ipynb` … `04_mbert_finetuning.ipynb` | your original English work | evidence; `test_alignment` relies on their outputs | — | **yes** | git (tracked) | Historical | move unchanged to `archive/early_experiments/` with a README (§4) |
| `notebooks/02_scoped_data_EDA.ipynb` | EDA of the Arabic SITR dataset (old scope) | nothing | — | historical | git | Uncertain | your decision (§9) |
| `notebooks/colab/05_round1_experiments.ipynb`, `06_round2_experiments.ipynb` | reproducible GPU rounds | Colab | — | yes | none | Active | keep |
| `scope.md` | old Arabic regex scope, already marked superseded | nothing | — | historical | git | Historical | replace with a two-line pointer to `docs/POLICY.md`, or move to `archive/` |
| `README.md` | project README | readers | — | — | git | Active | minimal fix done now; full rewrite at Step 10 |
| `requirements.txt` | `uv export` with hashes (165 packages, includes unused ones) | pip users | yes (`uv export`) | no | git | Active, stale | regenerate after the dependency cleanup |
| `requirements-colab.txt` | extra Colab packages, pinned and explained | Colab runner | — | — | none | Active | keep |
| `pyproject.toml`, `uv.lock` | packaging | install | — | — | git | Active | fixed now (§7); dependency cleanup in Phase 2 |
| `mbert_ner`, `evaluation/metrics.py`, `src/detectors/*`, `src/training/bio_alignment.py` | empty files and a "Hello" stub | nothing (confirmed: no imports, 0 bytes) | — | no | git history | Redundant | propose delete |
| `state/` | empty folder | nothing | — | no | — | Redundant | propose delete |
| `.vs/` | Visual Studio workspace state | IDE | yes | no | — | Local only | now git-ignored |

### 3.1 Scripts

| Group | Scripts | Status |
|---|---|---|
| Data | `build_eval_sets.py`, `build_synth_round2.py`, `audit_dataset.py`, `contamination.py`, `retarget_predictions.py` | Active |
| Train / predict | `train.py`, `predict.py` | Active |
| Evaluate / analyse | `evaluate.py`, `evaluate_system.py`, `analyze_round2.py`, `verify_round2.py`, `analyze_long_docs.py`, `operating_points.py`, `calibration.py` | Active |
| Pre-freeze studies | `verify_checkpoint.py`, `window_study.py`, `ipv4_gate_study.py` | Active (new) |
| Benchmark | `challenge_v2.py` | Active |
| Colab | `colab_runner.py`, `colab_round2.py`, `make_colab_bundle.py` | Active |
| Round 1 reproduction | `colab_round1.py`, `analyze_round1.py`, `reproduce_original_metric.py` (recomputes the original 0.9925) | Historical, still runnable; keep |

No script is unused. Duplication, checked by listing every function and class defined in more than one module:
* **`colab_round1.py` vs `colab_runner.py`: about 20 functions duplicated.** This is deliberate. `colab_round1.py` is the frozen Round 1 runner, kept byte-for-byte so notebook 05 reproduces the exact Round 1 bundle; `colab_runner.py` is its generalisation for Round 2.
  * **Option A (recommended):** keep it, labelled historical.
  * **Option B:** re-express Round 1 as a spec on `colab_runner.py`, as Round 2 is. That removes about 300 lines, but it changes the code that produced the Round 1 results.
* **`perturb.py` vs `synth.py`: names only.** Nine helpers share names (`_card`, `_iban`, `_phone`, …), but every implementation differs. They generate deliberately different value formats (format families A/B vs the Round 2 generator). Merging them would change generated, sha-pinned data, so they should stay as they are.
* **Small helpers:**
  * `sha256` appears in 3 scripts (`documents.file_sha256` already exists);
  * `mcnemar` appears in 2.

  Consolidating them into `runio.py` in Phase 2 is low-risk.
* A duplicated `ReplayModel` that I introduced in `ipv4_gate_study.py` was removed in Phase 1; it now imports the one in `evaluate_system.py`.

## 4. Your original notebooks (proposed archive notes)

All four English notebooks are kept **unchanged**. The proposed `archive/early_experiments/README.md` would state the following, and each notebook would get a one-line notice that is shown but does not alter its cells or outputs: "Historical experiment, not part of the current training or inference pipeline; see README in this folder."

| Notebook | What it did | Data | Later corrected | Still valid | Superseded by |
|---|---|---|---|---|---|
| `02_2scoped_data_EDA.ipynb` (49 cells, all with outputs) | Explored ai4privacy `pii-masking-200k`: language filter, entity and record coverage of the 13 labels, offset checks, data-quality and duplicate checks. Tokenizer exploration with mBERT offsets, BIO label functions v1/v2, manual chunking and boundary-crossing analysis | English ai4privacy | out-of-scope entities ignored (`-100`) rather than taught as O | descriptive statistics and quality checks; the boundary analysis motivated never cutting entities | `labels.py` (policies v2/v3), `alignment.py`, `scripts/audit_dataset.py` |
| `02_mbert_dataset_splitting.ipynb` | 80/10/10 split; label coverage per split; template-leakage detection and removal by moving shared templates; saved `data/processed/mbert_splits` | English (`data/raw/english_pii_43k.jsonl`) | names and values still repeat across splits (96–98% of names), so the test split measures template, not value, generalisation; addressed by the `test_unseen_*` slices | **yes: still the authoritative split** (`data/splits/original/*.ids`) | — (its output is still used) |
| `03_mbert_tokenization_and_alignment.ipynb` | Token/offset consistency, BIO validation and rebuild, label distribution, 512-token windows with 32 overlap; saved `data/processed/mbert_tokenized` | English | label policy v1 (`-100` for out-of-scope entities); windows evaluated as separate units | alignment and windowing are reproduced exactly by `alignment.training_features` (`tests/test_alignment.py`) | `alignment.py` + policy v3 |
| `04_mbert_finetuning.ipynb` | Colab fine-tuning of mBERT with HF Trainer (lr 2e-5, 2 epochs, best checkpoint by seqeval F1) → `checkpoint-4352`, validation F1 0.9925 | English (tokenised windows) | the 0.9925 was a metric artefact (out-of-scope entities invisible; corrected F1 0.643); `load_best_model_at_end` reported missing LayerNorm keys | the checkpoint is the Round 1 baseline (`mbert_original`); the training recipe (lr, epochs, batch) was kept | `scripts/train.py` (plain loop, reload validation), `reports/ROUND1_REPORT.md` |

New notebooks, if wanted for the final deliverable (an EDA of the current v3 data, a demo notebook), would be **new** files based on the authoritative pipeline, never edits of these.

## 5. Dependencies

| Declared in `pyproject.toml` | Imported by | Proposal |
|---|---|---|
| torch, transformers, numpy (via scripts), phonenumbers, seqeval, scikit-learn, datasets | package / scripts / tests | keep (core) |
| pytest | tests (dev group) | keep (dev) |
| presidio-analyzer, presidio-anonymizer, spacy, en-core-web-lg | `detectors/presidio_detector.py` (Round 1 baseline only) | move to an optional group `baselines` |
| en-core-web-sm | nothing (Presidio uses `lg`) | remove |
| pandas, ipykernel | notebooks only | optional group `notebooks` |
| matplotlib, seaborn | not imported anywhere (also not in the notebooks) | remove (or `notebooks` if you plan plots) |
| chromadb, faker, python-dotenv, streamlit | not imported anywhere | remove |

Each removal is verified in Phase 2 by:
* a fresh `uv sync`;
* the full test suite;
* the CLI and Python API;
* a predict and evaluate smoke run;
* the Colab bundle builder.

`requirements.txt` is then regenerated with `uv export`.

## 6. Data generations and backups

* **Raw source:** `english_pii_43k.jsonl` came from a Hugging Face Hub repository (download metadata: revision `7c22e681…`). Please confirm the repository id; the data README will cite it with the sha256.
* **Generations:**
  1. Your processed splits and tokenised windows (`data/processed`, policy v1).
  2. `data/eval` (policy v2, Round 1).
  3. `data/eval_v3` (policy v3, Round 2+).

  Generation 1 is historical and still proves the alignment. Generations 2 and 3 rebuild deterministically from the raw file + ids + scripts; the v3 rebuild was verified byte-identical on 2026-10-23.
* **Irreplaceable and not in git:** the raw file (HF Hub copy), `results/round1|round2` (archive zips in Downloads + Drive), the checkpoints (Drive only). Proposed: a committed `reports/ARTIFACTS.md` listing each archive and checkpoint with its location, size and sha256.

## 7. Phase 1 changes made (non-destructive)

| Change | Why | Verified by |
|---|---|---|
| `pyproject.toml`: `[tool.uv] package = true`; console script → `confidentiality_detector.__main__:main`; real description | CLI and package import were broken | `tests/test_cli.py` (5 tests): console-script target exists and matches the installed entry point; `python -m` runs outside the repository; BLOCK/ALLOW exit codes with values absent from output; configuration errors exit 2 |
| `uv.lock`: one line (`virtual` → `editable`); project installed editable with `--no-deps` | consequence of the above; no dependency version changed | `uv lock` diff; both entry points run from another directory |
| `__main__.py`: clear error when the default policy file is missing | the default is resolved from the source tree | test above |
| `README.md`: status and quick start corrected (the full rewrite stays for Step 10) | they described Round 2 as not run and an unusable command | review |
| `.gitignore`: `.vs/` | IDE state | — |
| `scripts/verify_checkpoint.py` (new); `challenge_v2.py freeze` reuses it | verify the real checkpoint **without** freezing anything | rejects a wrong checkpoint by predictions and by metadata (smoke run) |
| `scripts/window_study.py`: refuses to run unless the checkpoint is verified; reports entity, boundary and type-confusion errors; new safety criterion (entities caught on `validation_long` must not decrease) | your requirements for the study | `docs/METHODOLOGY.md` §7 amended before any result |
| `predict.py --stitching` | to re-predict all sets if a new window setting is adopted | — |
| IPv4 gate: `postprocess.py`, `policy.py` (`postprocessing` setting, validated), `pipeline.py` hook, `policy.json` (`"ipv4_requires_valid_address": false`), `scripts/ipv4_gate_study.py`; the frozen-system fingerprint includes the setting | approved for controlled testing; **off by default** | `tests/test_postprocess.py` (12 tests); criteria fixed in `docs/METHODOLOGY.md` §8 before any formal result |

The test suite went from 125 to 142 tests, all passing. No model output, BLOCK/ALLOW decision or default setting changed.

One design note for Phase 2: `configs/inference/policy.json` now holds both the security policy and the detector settings (windows, post-processing). One file is simpler to fingerprint and freeze, but the name undersells it. A rename to `system.json`, or a split into `policy.json` + `detector.json`, can be decided during consolidation.

## 8. Proposed version-control checkpoint (needs your approval)

**One commit before Phase 2.**
* **It would include** (about 14.5 MB):
  * `src/`, `scripts/`, `tests/`, `configs/`, `docs/`, `notebooks/colab/`;
  * `reports/*.md` and `reports/*.json`, plus `reports/runs_v3/`;
  * `data/dev/`, `data/challenge/` (frozen and hand-written);
  * `data/splits/original/`, `data/synth/round2/`, `data/eval/manifest.json`;
  * `data/eval_v3/` (8 MB; or manifests only, your choice);
  * `requirements-colab.txt`;
  * the modified `README.md`, `pyproject.toml`, `uv.lock`, `.gitignore` and `scope.md`.
* **It would exclude** (git-ignored): raw and processed data, `results/`, `predictions*/`, `dist/`, `checkpoints/`, `.vs/`, `.venv/`.
* **Before committing:** a scan for anything secret-like. The hand-written sets contain fictional values only.
* **Optional:** tag it `pre-consolidation` so Phase 2 can be undone completely.

## 9. Decisions needed from you

1. **`notebooks/02_scoped_data_EDA.ipynb`.** It is the Arabic SITR exploration (verified from its code and outputs). Keep it in the archive as the project's earliest exploration, clearly labelled, or remove it as part of the deleted Arabic work?
2. **The raw data's Hugging Face repository id**, for the data README.
3. **The checkpoint commit (§8):** approve, and choose whether `data/eval_v3/` is committed in full or as manifests only.
4. **After the inference studies, approve the Phase 2 list:**
   * the archive move (§4);
   * deleting the empty placeholders and `state/`;
   * deleting the duplicate `dist/colab_bundle.zip`;
   * the local `data/processed/*.zip` copies and HF cache files;
   * `scope.md`;
   * the dependency changes (§5);
   * the config naming (§7).
