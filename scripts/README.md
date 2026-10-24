# Scripts

Entry points, in pipeline order. Run from the repository root with the project environment (`uv sync`). Each script's docstring gives its exact usage. The package `src/confidentiality_detector/` holds the shared implementation; the scripts only orchestrate.

## Pipeline

| Step | Script | What it does |
|---|---|---|
| Data | `build_synth_round2.py` | Round 2 generated training and held-out data → `data/synth/round2/` |
| | `build_eval_sets.py` | every evaluation set from the raw file, the split ids and the hand-written sets → `data/eval_v3/` (`--policy v3`) |
| | `audit_dataset.py` | cross-split duplicates, value and template reuse, format realism → `reports/evidence/dataset_audit.json` |
| Training | `train.py` | one run from `configs/experiments/<run>.json`: integrity checks, training, epoch selection on validation, reload check |
| | `make_colab_bundle.py` | packs code and data, with per-file hashes, for a GPU round on Google Colab |
| | `colab_runner.py`, `colab_round2.py` | the Colab orchestration and the Round 2 specification (driven by `notebooks/colab/06_round2_experiments.ipynb`) |
| Prediction | `predict.py` | stores token probabilities and spans for a detector on evaluation sets (`--detector transformer|rules|presidio`) |
| Evaluation | `evaluate.py` | model-level or model + rules (`--hybrid-with`) metrics from stored predictions |
| | `evaluate_system.py` | the full BLOCK/ALLOW system: stored token probabilities replayed through `ConfidentialityDetector` (decoding, live rules, policy), with model, hybrid and system levels side by side |
| Freeze and benchmark | `verify_checkpoint.py` | proves that a local checkpoint reproduces its archived predictions |
| | `challenge_v2.py` | the independent benchmark: `validate`, `seal`, `contamination` and `freeze`, then a single ledgered `evaluate` |
| | `contamination.py` | similarity of a text set to all training data (used by `challenge_v2.py contamination`) |

## Round 1 reproduction (frozen)

* `colab_round1.py`: the Round 1 Colab runner (`notebooks/colab/05_round1_experiments.ipynb`). It is kept byte for byte so that Round 1 reproduces exactly; it calls `train.py`, `predict.py`, `evaluate.py` and `reproduce_original_metric.py` by path.
* `reproduce_original_metric.py`: re-scores the original notebook's checkpoint with the original token-level metric (0.9925) and with the corrected protocol.

## `analysis/`: the studies behind the reports

These are one-off analyses. They read stored predictions (no GPU; `window_study.py` needs the local checkpoint) and write `reports/evidence/`.

| Script | Evidence | Report |
|---|---|---|
| `analyze_round1.py` | `round1_analysis.json` | `reports/history/ROUND1_REPORT.md` |
| `verify_round2.py` | `round2_integrity.json` | `reports/history/ROUND2_REPORT.md` |
| `analyze_round2.py` | `round2_selection.json` (the selection rule, `docs/METHODOLOGY.md` §6) | ROUND2_REPORT |
| `analyze_long_docs.py` | `round2_long_docs.json` | ROUND2_REPORT §3 |
| `operating_points.py` | `operating_points_*.json` | ROUND2_REPORT, `docs/POLICY.md` §6 |
| `calibration.py` | `calibration_*.json` | ROUND1/ROUND2 reports |
| `window_study.py` | `window_study_r2_e3b_positive.json` | `docs/METHODOLOGY.md` §7 |
| `retarget_predictions.py` | (reuses predictions across evaluation-file versions with byte-identical texts) | `results/round2_derived/` |

The rejected IPv4 gate's study script was removed with the gate. Its evidence (`reports/evidence/ipv4_gate_study.json`) and decision (`docs/METHODOLOGY.md` §8) remain; the code is in commit `60897b3`.
