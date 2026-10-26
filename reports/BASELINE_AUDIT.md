# Baseline audit (inspection only)

**Date:** 2026-10-26. **Scope:** what baseline implementations and baseline results already exist in this repository, its Git history, its archived notebooks and its local (git-ignored) result folders.

**Method.** Inspection only. Git history (`git log`, `git show` of every commit), the archived notebooks, `reports/history/`, `reports/evidence/`, and the local git-ignored folders `reports/runs/`, `predictions/`, `predictions_v3/` and `dist/` were read. Stored metric files were *read*, never recomputed. **No detector was run, no prediction was made and no metric was computed for this audit.** Nothing in `results/`, `checkpoints/`, `configs/` or `src/` was modified.

Terms: **FA** = False ALLOW (protected document allowed), **FB** = False BLOCK (harmless document blocked). Entity scores are exact character-span micro P/R/F1 unless stated. "Not available" means no stored result exists; "Not evaluated" means the evaluation was never run.

---

## 1. Answers to the audit questions

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Did we implement a historical Regex-only baseline? | **Yes.** A regex detector for the project's original **Arabic** scope, committed on 2026-10-16. | commit `142f268` |
| 2 | Where is its implementation? | Only in Git history. It was removed on 2026-10-21 (commit `e93b2cd`, message: "remove the obsolete regex baseline and evaluation code"). Recover with `git show 142f268:src/detectors/regex_detector.py`, `git show 142f268:evaluation/metrics.py`, `git show 142f268:tests/test_regex_baseline.py`, `git show 142f268:tests/test_evaluation.py`. | §2 |
| 3 | Which labels and patterns? | 4 labels: `private_email` (generic e-mail), `private_phone` (Saudi mobile: `+966`/`00966`/`0` then `5` and 8 digits), `national_id` (10 digits starting with 1), `iqama` (10 digits starting with 2). Arabic-Indic and Persian digits normalised to ASCII; overlaps resolved earliest-then-longest; BLOCK if any match. | §2 |
| 4 | Was it evaluated previously? | **No evidence that it was ever run on a dataset.** Only 7 unit tests on hand-made strings exist. The planned benchmark notebook `notebooks/02_baseline_benchmark.ipynb` was **0 bytes** from its creation (`1c1d5c8`) to its deletion (`e93b2cd`), and no notebook at any commit imports the detector or its `evaluate()` function. | §2 |
| 5 | On which datasets and splits? | **None.** The README at `142f268` names `mabahboh/sitr-arabic-pii` (Arabic; train 14,288 / validation 1,818 / test 1,793 per the exploration notebook's output) as the intended dataset, but no evaluation on it is recorded. | `git show 142f268:README.md` |
| 6 | Which metrics were recorded? | **None recorded.** The code *defines* entity-level micro P/R/F1 (exact label + offsets) and message-level P/R/F1/accuracy with a confusion matrix, but no output was saved. | `git show 142f268:evaluation/metrics.py` |
| 7 | Are its original results reproducible from existing artifacts? | **There are no original results to reproduce.** The code is recoverable from Git and the dataset is public, so results *could* be produced, but that would be a new evaluation (not approved), and it would not be comparable with the final system (§5). | — |
| 8 | Do we have separate NER-only results? | **Yes, on development data only.** Transformer-only ("model" level) results exist for the original checkpoint, E1 and E2 (Round 1), R0–R4 (Round 2) and the final R3 on 13 sets. **Not available on `challenge_v2`.** | §3, §4 |
| 9 | Do we have Rules-v3-only results? | **Yes, on development data only:** 13 evaluation sets (label policy v3). Not computed for `validation_long` and `challenge_v1_final` (stored predictions exist), and **not evaluated on `challenge_v2`**. The stored rule predictions equal the frozen rules v3 output on every document checked. | §3, §4 |
| 10 | Which Regex / NER / Hybrid comparisons were performed? | Round 1: rules_v2 vs Presidio vs three transformers vs E2 + rules_v2, on the same v2 sets, with paired McNemar tests. Round 2 / final: rules_v3-only vs R3 model-only vs R3 + rules_v3 (hybrid = system `strict`) on the same v3 sets. `challenge_v2`: hybrid only (`strict`, `maximum`). | §4 |
| 11 | What baseline evidence is missing for the report? | No component-level (rules-only / NER-only) result on the independent benchmark; the historical Arabic regex was never evaluated; Presidio was not run under label policy v3 or on `dev_v1`. See §6. | §6 |

---

## 2. The four kinds of detector, kept apart

| | **A. Historical regex baseline** | **B. Later rule-based detectors (rules_v1 → v2 → v3)** | **C. Fine-tuned transformer only (NER-only)** | **D. Final hybrid system** |
|---|---|---|---|---|
| What | Regex for the original Arabic scope | Regex + checksum/format validators + context cues for the 13 English labels (`detectors/rules.py`) | mBERT-cased token classifier (27 BIO labels), argmax, no rules | R3 + rules v3, reconciled by `hybrid.merge`, plus the security policy (`strict`) |
| Language / labels | Arabic text; 4 Saudi-specific labels | English; 13 labels (rules never emit FIRSTNAME/LASTNAME; names and streets are left to the model) | English; 13 labels | English; 13 labels |
| Code today | Git history only (`142f268`) | **v3:** `src/confidentiality_detector/detectors/rules.py` (`RULES_VERSION = "v3"`, frozen). **v2:** no versioned copy in Git; an unversioned `rules.py` (200 lines, no version constant) inside the local `dist/colab_bundle_round1-r2.zip` is the Round 1 code, probably rules_v2 (not verified byte-for-byte against the v2 predictions). **v1:** source not preserved. | `detectors/transformer.py`; checkpoints outside Git (`reports/ARTIFACTS.md`) | frozen in `configs/inference/frozen_system.json` |
| Evaluated? | **No** | v1: validation only. v2: Round 1 sets + `dev_v1`. v3: 13 development sets | Development sets (Rounds 1–2, final) | Development sets **and** `challenge_v2` |
| Independent evaluation? | — | No | No | **Yes, `challenge_v2` only** |

**The final rules v3 is not the original baseline.** It is a separate English, 13-label detector written after the scope change, and it was refined on the `validation` and `dev_v1` sets (`reports/history/ROUND2_PLAN.md` §3). The historical regex baseline (A) shares no label definitions with it; even the phone pattern is Saudi-mobile-only.

### 2.1 Historical regex baseline in detail (commit `142f268`, 2026-10-16)

| Item | Content |
|---|---|
| Files | `src/detectors/regex_detector.py` (66 lines), `evaluation/metrics.py` (82 lines), `tests/test_regex_baseline.py` (5 tests), `tests/test_evaluation.py` (2 tests) |
| Patterns | `private_email`: `[\w.+-]+@[\w-]+(\.[\w-]+)+` with boundary guards; `private_phone`: `(+966\|00966\|0)5` + 8 digits with optional space/dash; `national_id`: `1` + 9 digits; `iqama`: `2` + 9 digits |
| Pre-processing | Arabic-Indic (٠–٩) and Persian (۰–۹) digits translated to ASCII; offsets refer to the original text |
| Decision | `classify_message`: BLOCK if any entity, else ALLOW |
| Metrics defined | entity micro P/R/F1 on `(label, start, end)`; message-level P/R/F1, accuracy, TP/FP/FN/TN |
| Tests | e-mail detection, Arabic-text phone with exact offsets (12–22), multiple entities, safe message → ALLOW, sensitive message → BLOCK; evaluation on 2 synthetic samples; a false positive is counted |
| Intended data | `mabahboh/sitr-arabic-pii` (README at `142f268`); scope `archive/scope_original.md` (11 Arabic-scope categories, of which the regex covered 4) |
| Removed | `e93b2cd` (2026-10-21), when the project moved to English `ai4privacy/pii-masking-200k` |

---

## 3. Timeline of baseline implementations and results

| Date | Commit / location | Event | Results stored? |
|---|---|---|---|
| 2026-10-07 | `1c1d5c8` | Empty placeholders: `regex_detector.py`, `ner_detector.py`, `presidio_detector.py`, `evaluation/metrics.py`, `02_baseline_benchmark.ipynb` (0 bytes) | — |
| 2026-10-16 | `142f268` | **Historical regex baseline** (Arabic, 4 labels) + metrics + 7 unit tests | **No** |
| 2026-10-17 to 20 | `67a3ff3`, `bda4d5a`, `5f563b8` | EDA: Arabic SITR data, then English `ai4privacy` (scope change) | — |
| 2026-10-21 | `e93b2cd` | mBERT notebooks added; regex baseline and its evaluation code **removed**; empty benchmark notebook deleted | — |
| ≈2026-10-22 | local, recorded in `predictions/*/run_info.json` (HEAD was `e93b2cd`; the code was not yet committed) | Round 0 investigation: **rules_v1** and **Presidio** run on the label-policy-v2 evaluation suite; **rules_v2** after validation-driven fixes | Yes: `reports/runs/` (git-ignored), summarised in `reports/history/INVESTIGATION.md` §4 |
| 2026-10-22 to 23 | `results/round1/` (Colab), `reports/history/ROUND1_REPORT.md` | **Round 1:** original checkpoint, E1, E2 (model-only) and E2 + rules_v2 (hybrid), compared with rules_v2 and Presidio | Yes |
| 2026-10-23 | `reports/history/ROUND2_PLAN.md` §3 | **rules_v3** (changes decided on `validation` and `dev_v1` only); rules_v3-only on 13 v3 sets | Yes: `reports/evidence/runs_v3/rules_v3/metrics.json` |
| 2026-10-23 | `results/round2/`, `reports/history/ROUND2_REPORT.md` | **Round 2:** R0–R4 at model, hybrid and system levels | Yes: `reports/evidence/round2_system_eval.json` |
| 2026-10-24 | `20ec277`, `5e7050b` | Package first committed (rules v3 included); final R3 metrics; freeze | Yes: `reports/evidence/final_system_metrics_r3.json` |
| 2026-10-25 | `c8300ec`, `reports/challenge_v2/` | Independent `challenge_v2`: hybrid `strict` and `maximum`, once each | Yes (aggregates only) |

---

## 4. Existing evaluation artifacts and verified numbers

All numbers below were **read from stored files**; none was recomputed.

### 4.1 Round 1 (label policy v2 evaluation suite, `data/eval/`)

Source: `reports/history/ROUND1_REPORT.md` §3 (tracked), from `reports/runs/<run>/metrics.json` (git-ignored, read for this audit). Entity exact F1; document FA rate / FB rate.

| Detector | Kind | `test` F1 | `test` FA / FB | `test_format_shift` F1 / FA | `challenge_v1` F1 | `challenge_v1` FA / FB |
|---|---|---:|---|---|---:|---|
| rules_v2 | rules only | 0.485 | 54.4% / 0.2% | 0.544 / 47.1% | 0.636 | 28.3% / 1.7% |
| Presidio (min score 0.3) | off-the-shelf PII baseline | 0.582 | 21.6% / 15.3% | 0.610 / 21.8% | 0.720 | 21.7% / 11.7% |
| original checkpoint-4352 | model only | 0.641 | 0.0% / 72.8% | 0.436 / 4.2% | 0.538 | 9.8% / 48.3% |
| E1 (policy v2) | model only | 0.984 | 0.1% / 1.0% | 0.566 / 10.5% | 0.652 | 19.6% / 20.0% |
| E2 (+ format augmentation) | model only | 0.984 | 0.1% / 1.1% | 0.603 / 2.8% | 0.728 | 7.6% / 16.7% |
| **E2 + rules_v2** | hybrid | 0.983 | 0.1% / 1.3% | 0.754 / 2.2% | **0.805** | **2.2%** / 18.3% |

`challenge_v1` here has 92 BLOCK / 60 ALLOW documents. Paired exact McNemar tests (ROUND1 §3): E2 + rules leaks less than Presidio on `challenge_v1` (discordant 1 vs 19, p < 0.001) and than the original model (p = 0.039).

**rules_v1** has a stored result on `validation` only (`reports/runs/rules_v1/metrics.json`, git-ignored): P 0.814, R 0.365, F1 0.504; FA 1,366/3,025 (45.2%), FB 133/1,154 (11.5%). Its predictions on the other v2 sets exist locally (`predictions/rules_v1/`) but were never scored, and its source code was not preserved.

### 4.2 Final level (label policy v3 evaluation suite, `data/eval_v3/`)

Sources: rules only, `reports/evidence/runs_v3/rules_v3/metrics.json`; model only and hybrid, `reports/evidence/final_system_metrics_r3.json` (hybrid = system `strict` on every document). The three detectors were scored on the same evaluation files (sha256 recorded in each prediction run and checked against `data/eval_v3/manifest.json`) with the shared `metrics.py`.

| Set | Rules v3 only: F1 · FA · FB | R3 model only: F1 · FA · FB | **R3 + rules v3 (`strict`)**: F1 · FA · FB |
|---|---|---|---|
| `validation` (3,017 B / 1,154 A) | 0.505 · 1,577 · 2 | 0.986 · 4 · 7 | 0.986 · 4 · 9 |
| `test` (3,055 / 1,068) | 0.481 · 1,677 · 1 | 0.985 · 3 · 10 | 0.984 · 3 · 11 |
| `test_format_shift` (3,055 / 0) | 0.539 · 1,463 · — | 0.746 · 46 · — | 0.804 · 45 · — |
| `test_long` (45 / 28) | 0.341 · 29 · 0 | 0.877 · 2 · 5 | 0.865 · 2 · 5 |
| `synth_A_heldout` (0 / 960) | — · — · 11 | — · — · 664 | — · — · 664 |
| `synth_B_heldout` (776 / 0) | 0.844 · 160 · — | 0.833 · 2 · — | 0.857 · 0 · — |
| `dev_v1` (56 / 75) | 0.676 · 18 · 1 | 0.649 · 0 · 27 | 0.685 · 0 · 27 |
| `challenge_v2` (200 / 200) | **Not evaluated** | **Not evaluated** | 0.677 · 2 · 70 |

Reading: the rules alone are precise and rarely over-block, but leak 21–64% of protected documents, depending on the set. The transformer alone catches far more. The hybrid has the lowest leakage on held-out formats and difficult positives (`test_format_shift` 45, `synth_B_heldout` 0), with about the transformer's false-block level (at most one more false block per set here).

### 4.3 Independent benchmark

`reports/challenge_v2/result_r2_e3b_positive_{strict,maximum}.json`: hybrid only. The result files have no breakdown by finding source (model vs rules), so no component attribution is possible on this set.

---

## 5. Are the comparisons methodologically fair?

| Comparison | Fair? | Caveats |
|---|---|---|
| Round 1: rules_v2 vs Presidio vs model-only vs hybrid | **Yes, within the round:** same evaluation files, same metric code, paired tests | rules_v1 test and `challenge_v1` per-class output were looked at once (disclosed, `INVESTIGATION.md` §3); rules_v2 tuned on validation; `challenge_v1` was written by the rules' author; Presidio's PERSON → FIRST/LAST split is heuristic (entity-level name scores understate it; document-level is the fairer comparison); how the 0.3 Presidio threshold was chosen is not recorded |
| Final level: rules_v3-only vs R3 model-only vs hybrid | **Yes as a development ablation:** same files, same metrics, rules verified identical to the frozen rules | Rules v3 were tuned on `validation` and `dev_v1`, and R3 was selected on `dev_v1`, so `dev_v1` numbers are optimistic for both. `test` and `test_format_shift` served as non-inferiority gates in the selection. **Not independent evidence.** |
| Historical Arabic regex vs anything else | **No comparison is possible or meaningful:** different language, dataset, label set; no results exist | — |
| Any component on `challenge_v2` | **No component-level comparison exists.** Only the frozen hybrid was evaluated, as pre-declared | — |
| Round 1 numbers vs final numbers | **Not directly comparable:** different label policies (v2 vs v3) and evaluation files | Report them as separate tables |

---

## 6. Missing information

| Missing | Status | Does the final report need it? |
|---|---|---|
| Historical regex baseline results (any dataset) | Not evaluated | **No.** Report it as the project's design-stage prototype for the abandoned Arabic scope, with "Not evaluated". |
| Rules-only and NER-only results on `challenge_v2` | Not evaluated (by design) | **No.** The benchmark was pre-declared for the frozen system; running other configurations on it would add evaluations to a sealed, already-used set and require the independent author. State the limitation instead. |
| Presidio under label policy v3, on `dev_v1` or `challenge_v2` | Not evaluated | No. Round 1 already positions Presidio. |
| Rules v3-only on `validation_long`, `challenge_v1_final` | Not computed (stored predictions exist for `validation_long`) | No. 13 other sets cover rules-only behaviour. |
| rules_v1 beyond `validation`; rules_v1 source code | Not computed; source not preserved | No. rules_v1 was superseded within a day. |
| Significance tests rules-only vs hybrid at v3 level | Not computed | No. The leakage differences are hundreds of documents on the synthetic sets. |
| Latency of the frozen system | Only Round 1 measurements (mBERT on the laptop CPU) | Report as such. |

---

## 7. Recommendation

**No additional baseline evaluation is necessary for the academic report.** The stored evidence already answers the question a baseline comparison is meant to answer (does the hybrid add value over regex/rules alone and over the transformer alone?), clearly labelled as **development-time evidence**:
* Round 1 (§4.1): rules_v2, Presidio, model-only and hybrid on identical sets, with significance tests;
* final level (§4.2): rules_v3-only, R3 model-only and R3 + rules v3 on identical sets, including the hand-written `dev_v1`.

The report should state plainly that the **only independent evidence is for the hybrid system**, and that the historical Arabic regex baseline was implemented and unit-tested but never evaluated.

**If the team nevertheless wants one more number,** the smallest experiment, needing **explicit approval** and **no model inference**:
* score the stored rules-v3 predictions on `validation_long` (`python scripts/evaluate.py --pred rules_v3 --pred-root predictions_v3 --eval-dir data/eval_v3 --sets validation_long --out-root <a new folder>`; a new output folder, so that the tracked `reports/evidence/runs_v3/rules_v3/metrics.json` is not overwritten): deterministic rules, existing predictions, CPU, seconds. It adds little.

**Not recommended:** running rules-only or model-only on `challenge_v2`, or running the historical Arabic regex on any set.

**Approval checkpoint:** nothing in this section has been run.
