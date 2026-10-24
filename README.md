# Confidentiality Detector

A local check that runs **before** an employee's prompt is sent to an external LLM. It finds information in 13 protected categories and returns **BLOCK** or **ALLOW**. Text never leaves the machine, and decisions never contain the detected values.

```
prompt ─► transformer (mBERT token classification, sliding windows) ─┐
       └► deterministic rules (validators + context cues) ───────────┴─► reconcile spans ─► security policy ─► BLOCK / ALLOW
```

Protected categories: `PASSWORD USERNAME EMAIL PHONENUMBER FIRSTNAME LASTNAME SSN CREDITCARDNUMBER CREDITCARDCVV IBAN ACCOUNTNUMBER STREET IPV4`. See `docs/POLICY.md` for exact scope and decisions.

## Status

| | |
|---|---|
| Selected candidate (round 2) | **R3 (`r2_e3b_positive`) + rules v3, `strict` mode**, chosen by the selection rule fixed before Round 2 ran. Hand-written `dev_v1`, full pipeline: False ALLOW 0/56 (95% CI 0–6.4%), False BLOCK 27/75; all false blocks are on deliberately constructed look-alike prompts (0/10 clean prompts blocked). Not yet frozen: a CPU-only inference study (window joining, IPv4 validation) comes first (`reports/ROUND2_REPORT.md`). |
| Why the original 0.9925 F1 was misleading | out-of-scope entities were invisible to the metric; the corrected F1 of the same model is 0.643 (`reports/ROUND1_REPORT.md`) |
| Independent evaluation | `challenge_v2`, written by a separate author, is evaluated once after the system is frozen (`docs/CHALLENGE_V2_SPEC.md`) |
| Real-world validation | **none yet**; all results are on synthetic or hand-written data (`docs/RISKS.md`) |

## Quick start

```bash
uv sync                                   # Python 3.13 environment; installs this package (editable)
python -m pytest -q                       # test suite
confidentiality-detector --model-dir <checkpoint dir> --file prompt.txt   # exit 0 = ALLOW, 10 = BLOCK, 2 = error
python -m confidentiality_detector --model-dir <checkpoint dir> < prompt.txt          # same, from stdin
```

Without uv: `pip install -e .` (Python 3.13), then the same commands. The CLI reads the default policy from `configs/inference/policy.json` in this checkout; pass `--policy` otherwise.

```python
from confidentiality_detector.pipeline import ConfidentialityDetector
detector = ConfidentialityDetector.load("<checkpoint dir>", "configs/inference/policy.json")
print(detector.inspect("please wire the deposit to DE89 3704 0044 0532 0130 00").to_dict())
```

Trained checkpoints are not in the repository (about 709 MB each). The selected R3 checkpoint is on Google Drive at `confidentiality_detector/round2/checkpoints/r2_e3b_positive`; download the folder unchanged to `checkpoints/r2_e3b_positive/` (git-ignored) and check it with `scripts/verify_checkpoint.py`. The Round 1 E2 checkpoint is at `confidentiality_detector/round1_rerun/checkpoints/e2_mbert_v2_fmtA`.

## Documentation

| Topic | Document |
|---|---|
| Product purpose, scope, person-name policy, ambiguous values, BLOCK/ALLOW logic, trade-offs | `docs/POLICY.md` |
| Per-label annotation rules | `docs/ANNOTATION_GUIDELINES.md` |
| Data sources, validation, splitting, alignment, windows, versioning | `docs/DATA_PIPELINE.md` |
| Training, evaluation, comparison and selection methodology | `docs/METHODOLOGY.md` |
| Modules and the inference data flow | `docs/ARCHITECTURE.md` |
| Case-file format; independent `challenge_v2` specification | `docs/CASE_FORMAT.md`, `docs/CHALLENGE_V2_SPEC.md` |
| What is and is not proven | `docs/RISKS.md` |
| Investigation history and results | `reports/INVESTIGATION.md`, `reports/ROUND1_REPORT.md`, `reports/COLAB_ROUND1_FIX.md`, `reports/ROUND2_PLAN.md` |

## Layout

```
src/confidentiality_detector/   labels (scope + annotation policy), documents, alignment, decoding, metrics,
                                perturb, synth, challenge, policy, pipeline, detectors/{transformer,rules,hybrid,presidio}
scripts/                        data builders, train, predict, evaluate, analysis, Colab runners, challenge_v2 tooling
configs/                        experiments/*.json (training runs), inference/policy.json (security modes)
data/                           raw (git-ignored), splits, eval (round 1, v2), eval_v3 (round 2), dev, synth, challenge
notebooks/                      original exploration and training notebooks; colab/ = reproducible GPU rounds
reports/                        findings, metrics, calibration, plans
tests/                          unit and integration tests
```

## Reproduce

```bash
python scripts/build_synth_round2.py                               # round-2 generated data
python scripts/build_eval_sets.py --policy v3 --out data/eval_v3   # round-2 evaluation suite
python scripts/predict.py --detector rules --name rules_v3 --eval-dir data/eval_v3 --out-root predictions_v3
python scripts/make_colab_bundle.py --round round2                 # GPU training happens on Colab:
#   notebooks/colab/06_round2_experiments.ipynb  (see reports/ROUND2_PLAN.md)
python scripts/analyze_round2.py --results results/round2          # after the Colab run
```
