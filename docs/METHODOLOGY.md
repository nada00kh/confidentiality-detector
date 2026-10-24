# Training and evaluation methodology

## 1. Baseline and lineage

| Run | Recipe | Status |
|---|---|---|
| `mbert_original` (checkpoint-4352) | mBERT, policy v1, HF Trainer | historical; corrected validation F1 0.643 |
| `e1_mbert_v2` | + label policy v2 | round 1 |
| **`e2_mbert_v2_fmtA`** | E1 + format-family-A augmentation (50% of target-bearing documents) | **round-1 winner; the round-2 baseline** (with rules: E2 + rules) |
| `r2_e2_v3` (R1) | E2 recipe + policy v3 (CVV evidence) | round 2, executed |
| `r2_e3a_hardneg` (R2) | r2_e2_v3 + `data/synth/round2/A_train.jsonl` | round 2, executed; fails leakage non-inferiority |
| **`r2_e3b_positive` (R3)** | r2_e2_v3 + `data/synth/round2/B_train.jsonl` | round 2, executed; **selected by the §6 rule** (with rules v3, `strict`) |
| `r2_e4_combined` (R4) | r2_e2_v3 + A + B | round 2, executed; passes 1–3 but not eligible under §6.4 |

Round 2 results and their verification: `reports/history/ROUND2_REPORT.md`.

**Fixed across all runs:**
* backbone: `google-bert/bert-base-multilingual-cased`;
* learning rate 2e-5, 2 epochs, batch 16, weight decay 0.01, warm-up 10%, fp16, seed 42;
* windows of 512 tokens with 32-token overlap;
* the original split.

Each round-2 run differs from its parent by exactly one factor. This is checked programmatically (`tests/test_colab_runner.py`, plus a config diff in `reports/history/ROUND2_PLAN.md`).

A **backbone change is not planned.** The confirmed weaknesses are data-coverage failures, and in-distribution F1 is already about 0.98. A backbone comparison is justified only if the data-centric runs leave important weaknesses unresolved.

## 2. Training procedure (`scripts/train.py`)

1. **Integrity checks before any GPU time.**
   * Configs are merged with explicit defaults.
   * Extra training files are checked against their manifest sha256, and each document against the scope and CVV rules.
   * The tokenizer must be a fast tokenizer.
   * Imports are checked at start-up, so a missing dependency fails in the first second.
2. **Features.** `alignment.training_features` builds the windows: the same code that the tests prove reproduces the original tokenised dataset.
3. **Loop.** Plain PyTorch with AdamW, a linear schedule and gradient clipping at 1.0. CUDA autocast in fp16 with a GradScaler. Length-bucketed shuffled batches. Training stops on a non-finite loss.
   * **AMP and the scheduler.** With fp16, GradScaler skips `optimizer.step()` when the scaled gradients overflow. This always happens at the first step or steps, and occasionally after each scale increase. Up to Round 2, the loop still advanced the learning-rate scheduler on skipped steps. That produced the logged warning "lr_scheduler.step() before optimizer.step()", and the schedule ran a few steps ahead of the real updates, out of 5,876–6,608.
     * `train.optimizer_step` now advances the scheduler only after a real update (a skipped step is detected by the scale decreasing, as in HF Accelerate). It counts skipped steps (`skipped_optimizer_steps` in the history and summary). `tests/test_training_loop.py` reproduces the old behaviour and checks the fix.
     * Round-1 and Round-2 checkpoints were trained with the old loop. Every run shared the same mechanism and the same seed, so their comparisons are unaffected.
4. **Per epoch.** Save the checkpoint first, then score the validation documents with the production decoder and metrics. Diagnostic sets (`dev_v1`) are logged but **never used for selection**.
5. **Selection.** Best validation entity F1, under the gold labels of the run's own policy.
6. **Checkpoint validation.** The selected epoch is **reloaded from disk** through the production loader, which fails on any missing or mismatched key or a wrong label mapping. It is re-scored, and the run fails unless the score matches. The Colab runner additionally checks the config label mapping, the weights and tokenizer files, and `reload_ok`.
7. **Recorded metadata.** `training_summary.json`: config, environment, data versions (raw/split/extra/eval manifests), per-epoch history, timing.

Colab orchestration (`scripts/colab_runner.py`) runs every step as a checked subprocess with full logs, validates artefacts before recording a stage as ok, resumes safely, and refuses to package incomplete rounds. The Round 1 failure analysis is in `reports/history/COLAB_ROUND1_FIX.md`.

## 3. Evaluation sets and their roles

| Set | Role | May influence decisions? |
|---|---|---|
| `validation` (synthetic) | epoch selection; rule changes | yes |
| `dev_v1` (hand-written, 135 cases) | model selection, operating points / security modes | **yes, this is what it is for** |
| `test`, `test_unseen_*`, `test_*_template`, `test_format_shift`, `test_long` (synthetic) | in-distribution, memorisation and format generalisation; regression | never tuned on; reported. `test` and `test_format_shift` were also **pass/fail non-inferiority gates** in the Round 2 rule (§6.1, §6.3), so they are not untouched. `test_long` was analysed in depth, which motivated §7, but never used to choose a setting |
| `synth_A_heldout`, `synth_B_heldout` (held-out generator families) | generalisation to unseen generation patterns | gates and benefit criteria in the Round 2 rule (§6.1–6.2) and the IPv4 gate study (§8); never tuned on |
| `validation_long` (79 concatenations of validation documents, 598+ tokens) | inference settings for long inputs (window length, §7) | yes, for inference settings only |
| `challenge_v1` / `challenge_v1_policy` / `challenge_v1_final` | regression and debugging; **not** independent evidence, because its failures were studied. `_policy` = final name policy (overlay v1, as Round 2 evaluated it); `_final` = + decision F (overlay v2) | report only |
| `challenge_v2` (hidden, independent) | final benchmark of the selected system | evaluated once per selected system; every evaluation is logged |

Synthetic results and hand-written results are always reported separately and never pooled. No result here is "real-world" validation (see `docs/RISKS.md`).

## 4. Metrics (`src/confidentiality_detector/metrics.py`)

* **Entity, strict.** Exact `(start, end, label)` character spans on the original document: precision, recall, F1, per-class P/R/F1/support/TP/FP/FN, and macro-F1. Predictions overlapping ignore spans are not counted. Predictions on out-of-scope look-alikes count as false positives.
* **Entity, lenient.**
  * Overlap recall: same type, any overlap.
  * **Caught (any type):** some prediction overlaps the gold span. This is the leakage-relevant measure.
* **Error taxonomy.**
  * Missed entities split into boundary, type confusion, and missed.
  * False positives split into boundary, type confusion, hard negative (by out-of-scope type), and spurious.
  * A type-confusion matrix.
* **Document.** BLOCK is the positive class.
  * BLOCK precision, recall and F1.
  * **False ALLOW rate** and **False BLOCK rate**, with Wilson 95% intervals.
  * The confusion matrix; AMBIGUOUS documents are excluded and counted.
* **Three levels of success per BLOCK document:**
  1. it is blocked (≥ 1 entity caught; BLOCK recall);
  2. **every** entity is caught (`block_docs_fully_caught`);
  3. every entity has the right type and boundaries (strict entity recall).
* **Per-tag** document results for the hand-written sets.
* **Calibration.** Span score (mean P(not O)) against correctness, by score bin (`scripts/analysis/calibration.py`).

Fixed correctness guarantees:
* no window-level scoring, so no duplicated or dropped entities;
* the ignore set is explicit and small (MIDDLENAME, MASKEDNUMBER, CVV_NO_EVIDENCE, AMBIG);
* predictions can only be scored against the exact evaluation file they were made on (`runio.check_provenance`);
* the old metric is still reproducible (`scripts/reproduce_original_metric.py`, row A = 0.9925), so the correction is auditable.

**Three evaluation levels**, always labelled:
* **model:** transformer spans only. The Colab notebook's metrics are at this level (`scripts/evaluate.py` without `--hybrid-with`).
* **hybrid:** model + stored rule predictions (`scripts/analysis/analyze_round2.py`).
* **system:** the real inference pipeline in a security mode (`scripts/evaluate_system.py` replays the stored token probabilities through `ConfidentialityDetector`: decoding, live rules, reconciliation, policy).

`system/strict` equals `hybrid` on every Round 2 document. Comparisons are only ever made within one level.

**Out-of-scope look-alikes count against the detector** (decision F). A prediction overlapping a negative span (`!TYPE`, including `!APIKEY`) is an entity false positive of type `hard_negative`. A blocked document without targets is a False BLOCK. Only `~` spans are excluded, and they may not be used for out-of-scope credentials.

## 5. Comparison and error-analysis procedure

* **Paired tests on the same documents.** Exact McNemar test on per-document correctness, separately for BLOCK documents (leaks) and ALLOW documents (false blocks). Bootstrap and Wilson intervals for rates. With 50–100 documents per class, differences of fewer than about 5 documents are usually not significant; this is reported, not hidden.
* **Error analysis.**
  * Per-class tables.
  * Per-tag document errors.
  * Listing every hand-written failure with its id, tags, missed or extra labels, the value *shape*, and the out-of-scope type it hit.
  * Attributing each false positive to its source (model or rules) and its confidence.
* **No tuning on report-only sets.** Thresholds, rules and model choices are fixed on validation and dev before held-out results are read. If a report-only set is looked at during development, that is disclosed (it happened once, in round 1, with `rules_v1`).

## 6. Round-2 selection rule (fixed before any round-2 result exists)

Every candidate is evaluated as **model + rules_v3, argmax decoding**, against its parent (R1 against E2; R2, R3 and R4 against R1).

1. **Leakage, primary; non-inferiority.**
   * On `dev_v1`: the candidate's false-ALLOW count ≤ the parent's + 1.
   * On `synth_B_heldout` and `test_format_shift`: False ALLOW rate ≤ the parent's + 0.5 percentage points, and not significantly worse (exact McNemar p < 0.05 counts as worse).
2. **Benefit, secondary.** A lower false-BLOCK count on `dev_v1`, or a lower False BLOCK rate on `synth_A_heldout` (hard-negative families). For experiment B: a lower False ALLOW rate on `synth_B_heldout` or `dev_v1`. R1 is a label-correctness fix, so it needs no benefit, only criteria 1 and 3.
3. **No in-distribution regression.** On `test`: entity F1 drop ≤ 0.005, and FAR and FBR each within ±0.5 percentage points.
4. **Adoption.**
   * A candidate replaces its parent if 1 and 3 hold and 2 shows a benefit.
   * R4 (A + B) is preferred over the single experiments only if R2 and R3 *both* satisfy 1, and R4 itself satisfies 1–3.
   * Otherwise the best single experiment wins.
   * Ties go to the simpler system.
5. **Operating point.** For the selected system, `scripts/analysis/operating_points.py` on `dev_v1` produces the False ALLOW / False BLOCK table over token thresholds and minimum span scores. The product owner picks the default (`strict`) and optional modes from that table. No false-block budget is assumed.
6. **Final.** The selected system and operating point are evaluated on `challenge_v2` (`scripts/challenge_v2.py evaluate`). That number is reported as is and is not used to change the system. If changes follow, `challenge_v2` becomes a development set and a new independent set is needed.

**Outcome (applied 2026-10-23, `reports/evidence/round2_selection.json`).**
* R1 passes against R0.
* R2 fails criterion 1: `synth_B_heldout` False ALLOW 0 → 26, and `dev_v1` 3 → 5.
* R3 and R4 pass criteria 1–3.
* Because R2 fails criterion 1, R4 is not eligible (§6.4), and the best passing single experiment, **R3**, is selected.
* The rule was applied as written. Its trade-off is analysed in `reports/history/ROUND2_REPORT.md` §7 rather than changed.

## 7. Inference windows for long inputs (fixed before any window result exists)

Two measured effects on `test_long` (`reports/history/ROUND2_REPORT.md` §3), for errors that do not occur on the same text in isolation:
* **Right-context starvation at the cut.** Round 1/2 stitching (`"first"`) lets the first window that contains a token predict it. The last tokens before a cut are therefore predicted with no right context, at window positions 478–509. The 32 tokens before the cut hold 4.3% of tokens but 7 of 11 context-only errors (R0), and 7 of 10 (R3).
* **Untrained positions.** 99.7% of supervised training tokens sit at positions 0–127. Almost all other context-only errors sit at positions ≥ 128.

`"centered"` stitching moves each cut to the middle of the overlap, so every token near a cut has at least overlap / 2 tokens of context on both sides. It uses the same model inputs; only the ownership of the overlap tokens changes. Shorter windows keep tokens in the trained position range, at the cost of less context.

`scripts/analysis/window_study.py` applies this rule mechanically to a local checkpoint. It first verifies the checkpoint against its stored Round 2 predictions on `dev_v1` and `test_long` (`scripts/verify_checkpoint.py`: identical spans, token probabilities within 1e-3), and refuses to run otherwise. For every candidate and set it reports False ALLOW, False BLOCK, entity precision, recall and F1, entities caught (any type), BLOCK documents fully caught, and boundary and type-confusion errors.

* **Candidates (max_length / overlap / stitching):**
  * 512 / 64 / first (baseline, as evaluated);
  * 512 / 64 / centered;
  * 256 / 64 / centered;
  * 128 / 32 / centered.

  Each is scored as model + rules, argmax (`strict`).
* **Adoption.** A candidate replaces the baseline only if all of the following hold:
  1. on `validation_long` it reduces False BLOCK without increasing False ALLOW, or reduces False ALLOW without increasing False BLOCK;
  2. on `validation_long`, the share of sensitive entities detected (caught, any type) does not decrease (safety check added 2026-10-24 at the product owner's request, before any window result existed);
  3. on `dev_v1`, False ALLOW does not increase and False BLOCK rises by at most 1;
  4. on `validation`, entity F1 drops by at most 0.005.
* **Choice.** Among adoptable candidates, the fewest `validation_long` errors wins (False ALLOW first), then the longer window. Otherwise the baseline stays.
* **Configuration.** The chosen setting is written to the `inference` section of `configs/inference/policy.json`, which `ConfidentialityDetector.load` uses and `challenge_v2.py freeze` fingerprints.
* `test_long` is reported only. The decision is made, and the system frozen, before `challenge_v2` is evaluated.

**Outcome (2026-10-24; `reports/evidence/window_study_r2_e3b_positive.json`).**

**Verification.** The local R3 checkpoint reproduced its archived predictions on `dev_v1` and `test_long`. Spans were identical, and token probabilities differed by at most 1.5e-5.

**Decision: all three candidates were rejected under criterion 1, and the baseline 512 / 64 / first is retained.** On `validation_long` the baseline is already at the ceiling for leakage: False ALLOW 0/49, every entity caught. Only 2 False BLOCKs out of 30 remained to improve, and no candidate changed a single BLOCK/ALLOW decision there.

| Set | Measure | 512/64/first | 512/64/centered | 256/64/centered | 128/32/centered |
|---|---|---|---|---|---|
| `validation_long` | FA / FB | 0 / 2 | 0 / 2 | 0 / 3 | 0 / 2 |
| `validation_long` | entity F1 | 0.956 | 0.962 | 0.944 | 0.956 |
| `dev_v1` | FA / FB | 0 / 27 | 0 / 27 | 0 / 27 | 0 / 27 |
| `validation` | entity F1 | 0.986 | 0.986 | 0.986 | 0.986 |
| `test_long` (report only) | FA / FB | 2 / 5 | 2 / 4 | 1 / 3 | 1 / 3 |
| `test_long` (report only) | entity F1 | 0.865 | 0.914 | 0.901 | 0.915 |

**What the result does not show.** The report-only `test_long` favours centered and shorter windows. It was not used for the decision, because that would make it a tuning set. Centered stitching improves entity precision on long inputs, but that did not translate into different decisions on the selection set. The selection set is small (79 documents) and has little headroom, so the study had little power to show a decision-level difference. This is recorded as a limitation and as future work (a larger long-document validation set), not as grounds to revise the rule after the fact.

## 8. IPv4 validation gate (fixed 2026-10-24, before the gate's formal evaluation)

> **Status: rejected; code removed.** The gate was evaluated under this section and not adopted (outcome below). On 2026-10-24 the product owner had its unused runtime code removed: `postprocess.py`, the `postprocessing` setting, `tests/test_postprocess.py` and `scripts/ipv4_gate_study.py`. Removing them left every decision unchanged. The code is preserved in commit `60897b3` (for example `git show 60897b3:src/confidentiality_detector/postprocess.py`). The rule, the evidence (`reports/evidence/ipv4_gate_study.json`) and the security reasoning stay here as the record.

**Status of prior evidence.** An exploratory check during the engineering review (2026-10-24) applied a stricter full-match variant of this gate to stored R3 predictions and saw `dev_v1` False BLOCK fall by 2 with no new leaks. That was exploratory and used `dev_v1`; it is **not** independent confirmation. `challenge_v2` remains the independent check.

**Behaviour** (as implemented until its removal: `src/confidentiality_detector/postprocess.py`, setting `postprocessing.ipv4_requires_valid_address` in `configs/inference/policy.json`, default `false`):
* A **model** span labelled IPV4 is kept only if it overlaps a complete IPv4 address in the text: four decimal octets 0–255, not part of a longer dotted or digit sequence.
* Rule findings are never removed. No other label is affected.
* There are no IBAN, card or SSN gates. They were not approved, because a failed checksum must not let a possibly sensitive value through.

**Evaluation** (`scripts/ipv4_gate_study.py`, removed after the decision; in commit `60897b3`):
* Run only after the window decision (§7), on predictions made with the final inference settings. The script refuses predictions made with other windows.
* The full pipeline is run with the gate off and on, in `strict` and `maximum`, on `dev_v1`, `validation_long`, `validation`, `test`, `test_format_shift`, `test_long`, `test_unseen_value`, `test_novel_template`, `synth_A_heldout`, `synth_B_heldout` and `challenge_v1_final` (the last as regression evidence only).

**Adoption.** The gate is switched on only if all of the following hold:
1. **No new leaks:** on every set and in both modes, no gold-BLOCK document that is blocked with the gate off is allowed with it on (zero tolerance).
2. **IPv4 detections preserved:** every gold IPV4 entity caught with the gate off is still caught with it on, on every set and in both modes.
3. **Integration:** rule findings are never removed, the policy layer is unchanged, and the setting is validated (`tests/test_postprocess.py`).
4. **Benefit:** `strict` False BLOCK decreases on at least one of `dev_v1`, `validation_long` or `synth_A_heldout`.

If any of 1–3 fails, or 4 shows no benefit, the gate stays off. A regression is recorded in the study report and not fixed by redesigning the gate against the same sets.

**Known residual risk.** A model span that mislabels another target as IPV4 (for example a dotted phone number) would be dropped. Criterion 1 measures this on every set, and the rules independently detect phone numbers.

**Outcome (2026-10-24; `reports/evidence/ipv4_gate_study.json`). The gate was NOT switched on.**

The study used the final windows (512 / 64 / first, §7). `validation_long` was predicted locally on the verified checkpoint; every other set came from the stored Round 2 predictions.

**Criteria.** All of them are met.
1. There is no new False ALLOW on any of the 11 sets, in either mode.
2. No gold IPV4 is lost.
3. The integration tests pass.
4. Strict False BLOCK falls on `synth_A_heldout`, from 664 to 606.

**Supplementary entity-level analysis.** Every removed finding overlapped no gold entity. Recall and entities caught are unchanged on every set; precision rises (`dev_v1` 0.559 to 0.576). Only software version strings were affected. No BLOCK/ALLOW decision changed on any set other than `synth_A_heldout`.

**Why it stays off.** The criteria are necessary, not sufficient ("switched on only if"). No evaluation set contains an IPv4 address written in a non-canonical form, so criteria 1 and 2 could not test that case. A probe with fictional RFC 5737 addresses (15 cases, recorded in the study report) shows the full pipeline turning BLOCK into ALLOW in both modes for:
* an address written with spaces (`192 . 0 . 2 . 17`);
* a mistyped address (an octet above 255);
* a three-octet prefix.

In each case the model had flagged the text as IPV4, the rules did not, and the gate discarded it. A formatting check would then let a possibly sensitive value through. That is the risk for which the IBAN, card and SSN gates were rejected, and False ALLOW is the primary concern. The benefit seen is confined to synthetic version strings.

Per this section, the gate is not redesigned against the same evidence.

**Limitation found by the probe (independent of the gate).**
* Defanged addresses (`[.]`, `(dot)`) and comma-separated octets are missed by both the model and the rules.
* Leading-zero and hostname-encoded addresses are blocked, but under the wrong label: PHONENUMBER and SSN.

These are recorded in `docs/RISKS.md` and the final limitations.
