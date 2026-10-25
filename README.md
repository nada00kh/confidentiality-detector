# Confidentiality Detector

A local check that runs **before** an employee's prompt is sent to an external LLM. It finds information in 13 protected categories and returns **BLOCK** or **ALLOW**. Text never leaves the machine, and decisions never contain the detected values.

**Scope:** English text; exactly 13 categories: `PASSWORD USERNAME EMAIL PHONENUMBER FIRSTNAME LASTNAME SSN CREDITCARDNUMBER CREDITCARDCVV IBAN ACCOUNTNUMBER STREET IPV4`. API keys and tokens, other languages, files and deliberately obfuscated text are out of scope (`docs/POLICY.md`, summary in `scope.md`).

```
prompt ─► transformer (fine-tuned mBERT, BIO token classification, sliding windows) ─┐
       └► deterministic rules v3 (validators + context cues) ─────────────────────────┴─► reconcile spans ─► security policy ─► BLOCK / ALLOW
```

## Status

| | |
|---|---|
| **Final system (frozen 2026-10-24)** | **R3 (`r2_e3b_positive`) + rules v3, `strict` mode**, windows 512/64/first, no extra validation gates. Recorded in `configs/inference/frozen_system.json` (sha256 of every checkpoint file, the policy, the inference code; code commit `4907107`). R3 was chosen by a selection rule fixed before Round 2 ran. |
| **Modes** | **`strict`** is the primary mode, used by the application. `maximum` is kept for reproducibility and research only, and is not offered to users (`reports/FINAL_REPORT.md` §6). |
| **Independent benchmark** (`challenge_v2`: 400 unseen cases by a separate author, sealed, evaluated once per mode on 2026-10-25) | **`strict`:** False ALLOW **2/200 (1.0%)**, False BLOCK **70/200 (35%)**; BLOCK F1 0.846; entity F1 0.677 (precision 0.544, recall 0.898). `maximum`: False ALLOW 1/200, False BLOCK 78/200. Most false blocks are harmless look-alike identifiers (tracking, serial, order and invoice numbers, versions) and out-of-scope secrets (`reports/FINAL_REPORT.md` §5). |
| **Development evidence** | Synthetic in-distribution test: entity F1 0.984, which says little about realistic text. Hand-written `dev_v1`: entity F1 0.685, False BLOCK 36%, consistent with the independent result. The original notebooks' 0.9925 F1 was a metric artefact (corrected: 0.643, `reports/history/ROUND1_REPORT.md`). |
| **Readiness** | **Research prototype, not production-ready.** No real employee prompts have been evaluated; one harmless prompt in three is blocked (`docs/RISKS.md`). |

## Quick start

Requirements: Git, [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python 3.13 and the exact versions in `uv.lock`), and the model checkpoint (below). Windows PowerShell:

```powershell
. .\scripts\dev_env.ps1 -Sync      # first time: create the environment from uv.lock and activate it
. .\scripts\dev_env.ps1            # any later session
python scripts/check_frozen_identity.py                     # is the local checkpoint/code the frozen detector?
"Please summarise the attached meeting notes." | python -m confidentiality_detector --model-dir checkpoints/r2_e3b_positive --mode strict
python -m pytest -q                                          # test suite
```

* **The environment** lives in `%LOCALAPPDATA%\confidentiality-detector\venv`, outside the repository, because OneDrive and similar sync clients interfere with virtual environments. The script only sets `UV_PROJECT_ENVIRONMENT` for the current session and activates it. VS Code terminals of this workspace get the same setting from `.vscode/`.
* **Outside synced folders, or on Linux/macOS,** `uv sync --frozen` with the default `.venv` works too. Without uv: `pip install -e .` (Python 3.13), with no pinned versions.
* **CLI exit status:** 0 = ALLOW, 10 = BLOCK, 2 = the detector could not be loaded. Input comes from `--file` or stdin.

```python
from confidentiality_detector.pipeline import ConfidentialityDetector
detector = ConfidentialityDetector.load("checkpoints/r2_e3b_positive", "configs/inference/policy.json", device="cpu")
decision = detector.inspect("please wire the deposit to DE89 3704 0044 0532 0130 00", "strict")
print(decision.decision, decision.categories)   # BLOCK ('IBAN',)
print(decision.to_dict())                       # categories, positions, reason; never the text or values
```

**Model checkpoint.** The weights (about 709 MB) are **not in Git**, and Git LFS is not used. The project owner shares the folder `r2_e3b_positive` privately. Place its six files in `checkpoints/r2_e3b_positive/` (git-ignored) and check them with `python scripts/check_frozen_identity.py`. The exact files and sha256 values are in `docs/INTEGRATION.md` §1.2. The model loads only from that folder (`local_files_only=True`); nothing is downloaded at inference time.

## Documentation

| Topic | Document |
|---|---|
| **Final results**: system, development evidence, independent benchmark, strict vs maximum, history, model card | `reports/FINAL_REPORT.md` |
| **Second computer and frontend/API integration**: setup, checkpoint, Python interface, fail-closed and privacy duties, frozen files | `docs/INTEGRATION.md` |
| Product purpose, scope, person-name policy, ambiguous values, BLOCK/ALLOW logic, trade-offs | `docs/POLICY.md` |
| Modules and the inference data flow | `docs/ARCHITECTURE.md` |
| Data sources, label policies, BIO alignment, augmentation, splits, versioning | `docs/DATA_PIPELINE.md` |
| Training, evaluation, selection rule, window and gate studies | `docs/METHODOLOGY.md` |
| Per-label annotation rules | `docs/ANNOTATION_GUIDELINES.md` |
| What is and is not proven; security risks | `docs/RISKS.md` |
| Case-file format; `challenge_v2` specification and the author handoff (v1.0, as given to the author) | `docs/CASE_FORMAT.md`, `docs/CHALLENGE_V2_SPEC.md`, `docs/CHALLENGE_V2_HANDOFF.md` |
| Investigation history, round reports, evidence; artifacts kept outside Git | `reports/README.md`, `reports/ARTIFACTS.md` |

## Layout

```
src/confidentiality_detector/   the package: labels (scope + annotation policy), documents, alignment, decoding, metrics,
                                perturb, synth, challenge, policy, pipeline, detectors/{transformer,rules,hybrid,presidio}
scripts/                        pipeline entry points (scripts/README.md); scripts/analysis/ = the studies behind the reports
configs/                        experiments/*.json (training runs); inference/policy.json and frozen_system.json (the frozen system)
data/                           hand-written sets, split ids and manifests; third-party and generated data stay local (data/README.md)
notebooks/colab/                the reproducible GPU training rounds (Google Colab)
reports/                        FINAL_REPORT.md, challenge_v2/ (the four aggregate benchmark files), history/, evidence/
archive/                        the original exploration and baseline notebooks, unchanged (archive/README.md)
tests/                          unit and integration tests
checkpoints/                    model weights, local only (git-ignored)
```

## Reproduce

Training runs on a GPU (Google Colab). Everything else runs on a CPU. The third-party raw data is not in Git: download it as described in `docs/DATA_PIPELINE.md` §0.

```bash
python scripts/build_synth_round2.py                               # round-2 generated data
python scripts/build_eval_sets.py --policy v3 --out data/eval_v3   # round-2 evaluation suite (needs the raw data)
python scripts/make_colab_bundle.py --round round2                 # GPU training happens on Colab:
#   notebooks/colab/06_round2_experiments.ipynb  (see reports/history/ROUND2_PLAN.md)
python scripts/evaluate_system.py --results results/round2 --detail      # full-system metrics from stored predictions
python scripts/challenge_v2.py verify-frozen --model-dir checkpoints/r2_e3b_positive   # only on the freezing computer (docs/INTEGRATION.md §1.6)
```

## Licence and data terms

* **No licence file.** The repository has none yet; adding one is the owners' decision.
* **Base model:** `google-bert/bert-base-multilingual-cased`, Apache-2.0.
* **Training data:** `ai4privacy/pii-masking-200k`, whose dataset card states no licence. Third-party data and data derived from it are therefore kept out of Git. Redistribution of the fine-tuned weights beyond the project team is unresolved (`docs/INTEGRATION.md` §9).
