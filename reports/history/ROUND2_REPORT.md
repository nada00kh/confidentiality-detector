# Round 2: verified results, investigation and selection

Round 2 ran on Colab (Tesla T4; torch 2.11.0+cu130, transformers 5.20.1) from bundle `round2-r1`. The archive `round2_results.zip` is extracted, unmodified, in `results/round2/`. Every number below was recomputed locally from the saved predictions and the gold files. No model was retrained for this analysis.

## 0. Summary

* **The archive is intact and the evaluation is sound.**
  * All 111 files match their recorded hashes, and the code that ran is byte-identical to the uploaded bundle.
  * All 65 (run × set) prediction files were made on exactly the local evaluation files.
  * The archived metrics reproduce exactly.
  * No stale prediction was evaluated: the evaluation-file mismatch bug is guarded and did not recur.
* **The notebook's R0–R4 numbers are transformer-only.** The pre-round-2 figure "2 false ALLOWs / 95" was E2 **+ rules**. At the same level, R0 reproduces it exactly: model-only 8/95, hybrid 2/95, full pipeline 2/95. Both levels are reported below and never mixed.
* **The pre-registered selection rule (`docs/METHODOLOGY.md` §6), applied unchanged, selects R3 (`r2_e3b_positive`) + rules v3.**
  * R2 (hard negatives) fails leakage non-inferiority.
  * That makes R4 (A + B) ineligible, although R4 passes every criterion against its parent.
* **R3 + rules is a genuine security improvement over the Round 1 system (E2 + rules), not a usability improvement:**
  * `dev_v1` False ALLOW 0/56 vs 5/56 (p = 0.06);
  * held-out formats 45 vs 61 of 3,055 (p = 0.014);
  * False BLOCK unchanged at 27/75 vs 28/75.
* **The main remaining weakness is false blocks on harmless identifiers:** `dev_v1` 36%, held-out hard-negative families 69%. They are high-confidence model errors that no threshold removes. R4's data removes most of them (`dev_v1` 16%), at a cost in leakage on format-shifted values that the security-first rule does not accept.
* **The long-document differences come from two measured effects, not from truncation or a merging error.**
  * Every model input is ≤ 512 tokens, and every token is predicted exactly once.
  * The 615 > 512 warning comes from the whole-document offset encoding, which never reaches the model.
  * **Effect 1, a stitching design flaw:** the last tokens before a window cut are predicted with no right context. The 32 tokens before the cut hold 4.3% of tokens but 7 of R0's 11 and 7 of R3's 10 errors that do not occur on the same text in isolation.
  * **Effect 2, untrained positions:** 99.7% of supervised training tokens sit at window positions 0–127.
  * A centered-stitching option and a pre-registered, CPU-only window study are prepared. The evaluated behaviour is unchanged until that study measures them.
* **The scheduler warning is caused by AMP skipping optimizer steps, not by wrong call order.**
  * A real but negligible deviation: the schedule runs a few steps ahead, out of about 6,000. It is fixed for future runs.
  * It does not compromise the comparisons: same mechanism and same seed in every run.
* **Recommendation:**
  * freeze R3 + rules v3, `strict` mode, as the candidate for `challenge_v2`;
  * no further GPU training is required for that;
  * two CPU-only steps remain: the long-input window study (recommended, rule fixed in advance; §3, §11) and freezing with verification (§13).

## 1. Artifact and data integrity (`scripts/verify_round2.py` → `reports/round2_integrity.json`)

| Check | Result |
|---|---|
| ZIP integrity (CRC), path safety | ok; 112 entries = 111 manifest files + `RESULTS_MANIFEST.json` |
| Every file vs `RESULTS_MANIFEST.json` sha256 | 111/111 match |
| Stages / smoke flag | R0–R4 `ok`, `smoke: false`, `complete: true` |
| Code that ran vs the uploaded `dist/colab_bundle_round2.zip` | 85/85 files identical (`BUNDLE_INFO.json`); Colab test suite 109 passed, 2 skipped (the alignment-equivalence tests need data not shipped to Colab; they pass locally) |
| Prediction provenance: eval sha256 recorded by `predict.py` vs local `data/eval_v3` | 13/13 sets ok for every run |
| Coverage: one row per document, no unknown or duplicate ids | ok for all 65 run × set files |
| Spans in bounds, in-scope labels, no duplicated or overlapping spans | ok |
| Every non-space character covered by a model token (no truncation) | ok |
| Stored spans = spans re-decoded from the stored token probabilities | ok |
| Archived metrics recomputed from predictions + gold | identical (0 differences) |
| Training data versions | raw data, split manifests and evaluation manifest identical for R1–R4; `A_train` / `B_train` sha256 match the local files; all reloaded checkpoints reproduce their validation score (`reload_ok`) |
| One factor at a time | R2/R3/R4 differ from R1 only in `extra_train`; R1 differs from E2 only in `label_policy` v2 → v3 (plus the logging-only `diagnostic_sets`) |
| R0 used the intended checkpoint | its predictions equal the Round 1 E2 predictions on all 10,035 documents of the 6 sets whose text did not change |

**Evaluation configuration.**
* Notebook metrics: transformer spans, argmax decoding, 512-token windows with 64 overlap, gold annotation policy v3 (CVV evidence rule), final person-name policy (`challenge_v1_policy`).
* No security policy and no rules were applied in the notebook. Rules and policy are applied locally in §5.

**Excluded and ambiguous cases.**
* `dev_v1`: 135 cases = 56 BLOCK + 75 ALLOW + 4 AMBIGUOUS. The ambiguous ones are excluded from document metrics:
  * `amb-001`: a bare short number;
  * `amb-002`: a numeric meeting passcode;
  * `amb-003`: CIDR ranges;
  * `amb-004`: fictional characters.

  So False ALLOW = x/56 and False BLOCK = x/75. No system flags any of the 4.
* `challenge_v1_policy`: 95 / 56 / 3 ambiguous.
* `test`: 3,055 / 1,068 / 226 ambiguous (documents whose only annotations are ignore spans: MIDDLENAME, masked numbers, CVVs without evidence).
* `synth_A_heldout` is ALLOW-only (960) and `synth_B_heldout` is BLOCK-only (776).

**The evaluation-file mismatch bug did not recur.** Every prediction file passed `check_provenance` against the exact local file. R0 re-predicted the sets whose v3 text changed (`test_long`, `test_format_shift`, `test_unseen_value`) instead of reusing Round 1 predictions.

## 2. What each experiment changed

| | R0 `e2_mbert_v2_fmtA` | R1 `r2_e2_v3` | R2 `r2_e3a_hardneg` | R3 `r2_e3b_positive` | R4 `r2_e4_combined` |
|---|---|---|---|---|---|
| Training | none (Round 1 checkpoint) | E2 recipe | R1 + `A_train` | R1 + `B_train` | R1 + A + B |
| Gold policy in training | v2 | **v3** (CVV needs evidence) | v3 | v3 | v3 |
| Base documents (original split) + format-A copies | 34,802 + 12,222 | 34,802 + 12,196 | same as R1 | same | same |
| Extra documents | — | — | 3,173 hard negatives | 2,687 difficult positives | 5,860 |
| Windows / optimizer steps | — | 47,002 / 5,876 | 50,175 / 6,272 | 49,689 / 6,212 | 52,862 / 6,608 |
| Train loss, epoch 1 → 2 | — | 0.108 → 0.0027 | 0.105 → 0.0026 | 0.108 → 0.0030 | 0.106 → 0.0023 |
| Validation entity F1 (v3 gold), epoch 1 → 2 (selected) | — | 0.983 → **0.990** | 0.974 → **0.985** | 0.981 → **0.986** | 0.980 → **0.989** |
| `dev_v1` entity F1, model-only (diagnostic, not used for selection) | 0.430 | 0.404 → 0.450 | 0.403 → 0.474 | 0.579 → 0.649 | 0.692 → 0.703 |
| Wall time | 2 min (predict) | 14 min | 15 min | 15 min | 15 min |

* **Fixed across runs:** mBERT-cased initialisation with a fresh classification head (the load report's "UNEXPECTED" pooler/MLM keys and "MISSING" classifier keys are expected); learning rate 2e-5; 2 epochs; batch 16; warm-up 10%; fp16; seed 42; 512/32 training windows; format-A augmentation of 50% of target-bearing documents.
* **A consequence of the policy change that is not a separate factor:**
  * v3 removes 52 documents' only "targets" (CVVs without evidence), so 26 fewer documents are augmented.
  * The augmentation draw shifts accordingly.
* **A_train:**
  * 2,693 target-free documents plus 480 from three mixed families (FIRSTNAME 160, EMAIL 160, IPV4 160, LASTNAME 76);
  * top look-alike types: short numbers 799, versions 640, tracking 543, tickets 482, order IDs 406, SKUs 265, meeting IDs 244, company IDs 238, invoices 235, error codes 199, PINs 160.
* **B_train:**
  * USERNAME 1,008, PASSWORD 773, FIRSTNAME 636, LASTNAME 531, CVV 319 (all with evidence), EMAIL 205, IPV4 163, SSN 160, card 159, IBAN 86, STREET 84, ACCOUNTNUMBER 74, PHONE 47.
* **Round 2 data checks:**
  * no training text occurs in any evaluation set;
  * `dev_v1` and `challenge_v1` share no target value with `A_train`/`B_train`;
  * **but 20% of `synth_B_heldout`'s target values (235/1,192: usernames, names, CVVs) also occur in `B_train`**, because the generator draws from the same value pools. `synth_B_heldout` therefore tests unseen *templates*, partly with memorised values, and flatters B-trained models (R3, R4). The selection outcome does not depend on it: R1, R3 and R4 all have 0 hybrid leaks there, and R3's benefit came from `dev_v1`.
* **A semantic tension, not an annotation contradiction.** A_train teaches that short numbers, product and company names and IDs are O. That also suppressed real difficult positives in R2: on `synth_B_heldout`, model-level LASTNAME recall fell 0.51 → 0.25 and USERNAME 0.49 → 0.33. On held-out formats, CVV recall fell 0.26 → 0.23. This is why R2 leaks.
* **`synth_A_heldout` entity F1 = 0 is not a model failure.** The set has no target entities, so every prediction is a false positive and entity precision, recall and F1 are 0 or undefined by construction. Only its False BLOCK rate is meaningful.

## 3. Long documents (`scripts/analyze_long_docs.py` → `reports/round2_long_docs.json`)

**What `test_long` is.** 73 documents, each the concatenation of 12–18 standalone `test` documents:
* 45 BLOCK: one PII-bearing document hidden among target-free ones;
* 28 ALLOW: target-free documents only, which carry out-of-scope PII such as dates, URLs and crypto addresses.

Each document is 598–942 tokens, i.e. exactly 2 inference windows. Every component also exists alone in `test.jsonl` with byte-identical text, so each long-document error can be compared with the prediction on the same text in isolation.

**Mechanics: no truncation, offset error or duplicate detection.**
* All 146 model inputs are ≤ 512 tokens.
* Every token is owned by exactly one window, and every non-space character is covered.
* No predicted span crosses a component boundary or is duplicated.
* Stored spans equal those re-decoded from the stitched probabilities.

The stitching *design*, however, has a measurable weakness (below).

**Errors in context vs. in isolation (model-only):**

| | FP spans | of which also in isolation | missed entities | caught in isolation | False BLOCK docs (from isolation) | False ALLOW docs |
|---|---|---|---|---|---|---|
| R0 | 18 | 7 | 0 | — | 4 (6) | 0 |
| R1 | 13 | 6 | 0 | — | 5 (4) | 0 |
| R2 | 32 | 4 | 1 | 1 | 9 (4) | 1 |
| R3 | 16 | 7 | 2 | 1 | 5 (4) | 2 |
| R4 | 8 | 5 | 2 | 2 | 2 (4) | 1 |

Most long-document errors do not occur on the same text alone. Two effects explain them.

**Effect 1: right-context starvation at the window cut (a stitching design flaw).**
* The Round 1/2 stitching lets the *first* window that contains a token predict it. The window after the cut re-reads 64 tokens of left context but predicts only tokens after the cut.
* So the last tokens before the cut are predicted with no right context, at window positions 478–509.
* The 32 tokens before the cut are 4.3% of all tokens, yet they hold this share of errors:

  | | All model errors | Context-only errors |
  |---|---|---|
  | R0 | 8 of 18 | 7 of 11 |
  | R1 | 5 of 13 | 4 of 7 |
  | R2 | 8 of 33 | 7 of 29 |
  | R3 | 9 of 18 | 7 of 10 |
  | R4 | 2 of 10 | 1 of 5 |

* That is roughly ten times the base rate. The document start and end zones (4.3% each) hold 0–1 errors.
* **Fix prepared, not yet adopted.** `inference_windows(..., stitching="centered")` moves each cut to the middle of the overlap, giving every token near a cut at least 32 tokens of context on both sides. Model inputs are identical; only the ownership of overlap tokens changes (`tests/test_alignment.py`).
* Its effect cannot be computed from the stored probabilities, because the second window's predictions for overlap tokens were not kept. It needs the checkpoint locally (§11). Until it is measured, the evaluated `"first"` stitching stays the default.

**Effect 2: untrained positions.**
* **99.7% of supervised training tokens are at window positions 0–127.** Training windows have a median of 47 tokens, and `A_train`/`B_train` documents are at most 78 tokens.
* Positions 0–127 hold 26% of `test_long`'s tokens but only 0–2 context-only false positives per run. The rest are at positions ≥ 128 (R0: 11 of 11; R2: 26 of 28), including the cut zone.
* Example: `long-block-044` is a surname that starts a component ("⟨surname⟩, plan to attend …"), at token 168 of window 1, far from any edge.
  * R0 and R1 still catch it (0.95 / 0.92, versus 0.999 alone).
  * R2–R4 miss it in context but catch it alone.
* Shorter inference windows (256 or 128 tokens) would keep tokens in the trained range; they are candidates in the same study. The training-side remedy is packed multi-document training windows (GPU).

**R2's extra false blocks (9 vs R1's 5).**
* 27 of R2's 32 false-positive spans are PASSWORD, mostly fragments of crypto addresses (25 spans hit Bitcoin, Ethereum or Litecoin addresses).
* 22 of its 29 context-only errors lie away from the cut, mostly at positions 128–255.
* R2 does not produce them in isolation. The hard-negative data made the model more context-dependent in a way that does not transfer to untrained positions.
* **R3/R4's false ALLOWs.**
  * `long-block-044` (R2, R3, R4) is the context/position effect above.
  * `long-block-023` (R3 only) is a plain R3 miss: R3 also misses that name alone.
* **Accumulation.** A long ALLOW document is blocked when any of its 12–18 components triggers. From isolation alone, 4–6 of 28 would be blocked, depending on the model. The remainder are the two context effects above.
* **Statistical weight is small.** 45 / 28 documents: R0 vs R3 False ALLOW 0 vs 2 (p = 0.5); R1 vs R2 False BLOCK 5 vs 9 (p = 0.29).
* **The `dev_v1` and challenge comparisons are not confounded.** Their documents are short (median 24–26 tokens), and all but 2–3 of their errors lie in positions 0–127.

**The warning "Token indices sequence length is longer than … (615 > 512)".**
* `alignment.encode_text` tokenises each whole document once, untruncated, to obtain character offsets. The tokenizer warns whenever that sequence exceeds 512 tokens.
* 615 is a training document (4 of 46,998 exceed 510 tokens and become 2 windows); 683 is a validation document.
* Those sequences are then split by `plan_windows` and never reach the model.
* **Proof:**
  * a replay of the exact construction on all 13 evaluation sets and on `A_train`/`B_train` gives a maximum model input of 512;
  * BERT cannot accept more than 512 positions (it would have crashed);
  * the end-to-end test now records every model input with a forward hook on a 1,000+ token document.
* **Change:** the tokenizer call passes `verbose=False`, and explicit guards now reject any model input over `max_length` (`training_features`, `wrap_window`) and any `max_length` above the model's position limit (`TransformerDetector`).

## 4. Training warnings

* **"Detected call of `lr_scheduler.step()` before `optimizer.step()`".**
  * The loop calls `scaler.step(optimizer)` before `scheduler.step()`, so the order is correct.
  * PyTorch emits this warning only when, at the first scheduler step, the optimizer has not stepped. That happens when the fp16 GradScaler skips an overflowing step: always at the start, while the loss scale (initially 65,536) calibrates.
  * The old loop advanced the scheduler on skipped steps anyway, so the schedule ran ahead by the number of skipped steps. That is typically a handful (the initial calibration plus at most one after each of the ~3 scale increases per run), out of 5,876–6,608.
  * **Effect:** the learning rate at each real update corresponds to a step a few positions later in the schedule. That is < 2% during the 588–661-step warm-up and ≈ 0.1% afterwards. The skipped batches are simply not learned from.
  * The same mechanism, data order and seed applied to every run, so it does not bias the comparisons. Its size is far below the effects measured here.
  * The exact number was not logged in Round 2.
  * **Fixed for future runs:** `train.optimizer_step` advances the scheduler only after a real update and logs `skipped_optimizer_steps` and the learning rate per epoch. `tests/test_training_loop.py` reproduces the skip on CPU and checks the fix.
  * **No retraining was done or is needed for this.**
* **Harmless:**
  * the BERT load report: unexpected pooler/MLM-head keys and a missing classifier, which is a freshly initialised head, as intended. Checkpoint reloads load all 199 tensors, and reload validation passes.
  * "unauthenticated requests to the HF Hub": a download-rate notice.
  * The progress bars.
* **No other warnings or errors appear in the 17 logs.**

## 5. Model-only vs hybrid vs full pipeline: the 8/95 vs 2/95 discrepancy

The notebook ran `scripts/evaluate.py` without `--hybrid-with`, so its metrics are **transformer-only**. The product is the full pipeline. `scripts/evaluate.py` and `scripts/evaluate_system.py` report three levels:

* **model:** transformer spans only, exactly the notebook numbers.
* **hybrid:** model + stored rules v3 predictions.
* **system:** the stored token probabilities replayed through `ConfidentialityDetector` (decoding at the mode's threshold, live rules v3, span reconciliation, security policy), in `strict` and `maximum`.

`system/strict` = `hybrid` on every document of every set. The live rules reproduce the stored rule predictions on all 12,456 documents checked (10 sets).

`challenge_v1_policy` (95 BLOCK / 56 ALLOW), False ALLOW / False BLOCK:

| | model | hybrid = system/strict | system/maximum |
|---|---|---|---|
| R0 = E2 | 8 / 8 | **2 / 8** (the pre-round-2 baseline, reproduced) | 0 / 10 |
| R1 | 8 / 8 | 2 / 8 | 1 / 10 |
| R2 | 17 / 1 | 6 / 1 | 5 / 4 |
| R3 | 4 / 7 | 2 / 7 | 0 / 10 |
| R4 | 6 / 4 | 2 / 4 | 1 / 5 |

The rules remove most model-level leaks (structured values: e-mails, cards, IBANs, passwords in JSON). The best transformer is therefore not automatically the best system: R4 has the best model-level `dev_v1` F1 (0.703) but is not the safest system. `challenge_v1` is a regression set whose failures were studied; it is not used for any decision here.

## 6. Results

**`dev_v1`** (hand-written; 56 BLOCK / 75 ALLOW; 4 ambiguous excluded). Cells show False ALLOW, False BLOCK, entity F1:

| | model (notebook) | system / strict | system / maximum | BLOCK docs fully caught (strict) |
|---|---|---|---|---|
| R0 | 8 (14.3%), 28 (37.3%), 0.430 | 5 (8.9%), 28 (37.3%), 0.584 | 3, 33, 0.549 | 83.9% |
| R1 | 5, 24, 0.450 | 3 (5.4%), 24 (32.0%), 0.609 | 2, 28, 0.571 | 85.7% |
| R2 | 17, 8, 0.474 | 5 (8.9%), 8 (10.7%), 0.689 | 4, 11, 0.667 | 80.4% |
| **R3** | **0**, 27, 0.649 | **0 (0.0%, CI 0–6.4%)**, 27 (36.0%, CI 26–47%), 0.685 | 0, 32, 0.667 | **96.4%** |
| R4 | 5, 11, 0.703 | 3 (5.4%, CI 1.8–14.6%), 12 (16.0%, CI 9.4–25.9%), 0.762 | 1, 13, 0.707 | 92.9% |

The notebook's `dev_v1` rates are reproduced exactly: 8/56 = 0.1429, 28/75 = 0.3733, and so on.

**Other sets, system/strict** (FA = False ALLOW, FB = False BLOCK, with their denominators):

| Set | R0 | R1 | R2 | R3 | R4 |
|---|---|---|---|---|---|
| `test` (in-distribution) FA/3,055, FB/1,068, F1 | 3, 13, 0.983 | 3, 10, 0.985 | 6, 14, 0.980 | 3, 11, 0.984 | 1, 12, 0.986 |
| `test_format_shift` FA/3,055 (model FA) | 61 (78) | 68 (79) | 69 (135) | **45** (46) | 67 (72) |
| `test_long` FA/45, FB/28 | 0, 4 | 0, 5 | 1, 9 | 2, 5 | 1, 2 |
| `synth_B_heldout` FA/776 (model FA) | 0 (80) | 0 (40) | 26 (193) | 0 (2) | 0 (18) |
| `synth_A_heldout` FB/960 | 674 | 612 | 124 | 664 | **187** |
| `test_unseen_value` FA/1,931 | 0 | 0 | 0 | 0 | 0 |
| `test_novel_template` FA/542, FB/277 | 0, 2 | 0, 2 | 0, 2 | 1, 2 | 0, 2 |

**Per class** (`dev_v1`, system/strict, recall). R3 gains most on the difficult positives B targets:
* PASSWORD 0.38 → 0.77 (R0 → R3; n = 13);
* FIRSTNAME 0.50 → 0.81 (16);
* USERNAME 0.82 → 0.94 (17).

All other classes are at 1.00 for every run except ACCOUNTNUMBER (0.50, n = 2), LASTNAME (0.60–0.80) and STREET (0.5–1.0, n = 2). Precision is low for PHONENUMBER, SSN, IPV4 and ACCOUNTNUMBER in R0, R1 and R3: hard-negative false positives, which R2 and R4 reduce.

On held-out formats, R3's CVV recall is 0.71 (R1 0.26) and its PASSWORD recall is 0.87 (R1 0.58). Full tables are in `reports/round2_system_eval.json`.

**Where R3's false blocks come from** (`dev_v1`, 27 documents):
* 33 of 34 findings come from the model, 1 from model + rules;
* median span score 0.988;
* the targets hit are tracking, meeting and order IDs, versions, SKUs, vendor/company IDs, error codes, arithmetic and product names (as FIRSTNAME).

Calibration (`reports/calibration_r2_e3b_positive.json`): 68% of R3's `dev_v1` false-positive spans and 83% of its `synth_A_heldout` ones score ≥ 0.9. No threshold separates them from true positives.

## 7. Selection rule outcome (`scripts/analyze_round2.py` → `reports/round2_selection.json`)

Applied mechanically, as written before any result existed (model + rules v3, argmax):

| Candidate vs parent | 1. Leakage non-inferiority | 2. Benefit | 3. No in-distribution regression | Result |
|---|---|---|---|---|
| R1 vs R0 | pass (`dev_v1` FA 3 vs 5; format shift 68 vs 61 = +0.23 pp, p = 0.40) | not required (label fix) | pass | **pass** |
| R2 vs R1 | **fail:** `synth_B_heldout` FA 26 vs 0 (p = 3×10⁻⁸); `dev_v1` FA 5 > 3 + 1 | `dev_v1` FB 8 vs 24 | pass | **fail** |
| R3 vs R1 | pass (`dev_v1` 0 vs 3; format shift 45 vs 68, p = 0.0003) | `dev_v1` FA 0 < 3 | pass (F1 −0.001) | **pass** |
| R4 vs R1 | pass (`dev_v1` 3 vs 3; format shift 67 vs 68) | `dev_v1` FB 12 < 24 (p = 0.004) | pass | **pass** |

**Adoption (§6.4).**
* R4 is preferred only if R2 **and** R3 both satisfy criterion 1. R2 does not, so R4 is not eligible.
* The best passing single experiment is the only one: **R3**.
* The outcome is robust to the rule's thresholds: R2's failure is large, not a one-document margin.

**The rule worked as designed, but the trade-off it encodes should be explicit.** R3 vs R4, paired, system/strict:

| | R3 | R4 | Exact McNemar |
|---|---|---|---|
| `dev_v1` False ALLOW | 0/56 | 3/56 | p = 0.25 (not significant) |
| `test_format_shift` False ALLOW | 45 | 67 | **p = 0.001 (R3 better)** |
| `test_long` False ALLOW | 2/45 | 1/45 | p = 1.0 |
| `dev_v1` False BLOCK | 27/75 | 12/75 | **p = 0.0003 (R4 better)** |
| `synth_A_heldout` False BLOCK | 664/960 | 187/960 | **p < 10⁻⁹⁹ (R4 better)** |
| `test_long` False BLOCK | 5/28 | 2/28 | p = 0.25 |

* Security-first, R3 is the defensible choice. It has the lowest observed leakage on the development set, and significantly lower leakage on unseen value formats.
* R4 would cut false blocks by more than half, but it leaks more on unseen formats.
* Moving to R4 would mean re-weighting security against usability. That is a product decision, not something to infer from these numbers, and it would have to be taken **before** `challenge_v2`. It has not been taken.

**R3 + rules vs the Round 1 system E2 + rules (R0), same pipeline and data:**
* False ALLOW:
  * `dev_v1` 0 vs 5 (p = 0.06);
  * format shift 45 vs 61 (p = 0.014);
  * `test` 3 vs 3; `synth_B` 0 vs 0;
  * `test_long` 2 vs 0 (p = 0.5).
* False BLOCK:
  * `dev_v1` 27 vs 28 (p = 1.0);
  * `synth_A` 664 vs 674 (p = 0.42).
* No unacceptable confidentiality regression was found. The one adverse direction, `test_long` False ALLOW 0 → 2 of 45, is not significant, and one of the two misses is the position effect of §3.

## 8. Security modes and operating point (`dev_v1` only)

`scripts/operating_points.py` for R3 + rules v3 (`reports/operating_points_r2_e3b_positive__rules_v3_dev_v1.json`):

| Token threshold | Min span score | False ALLOW /56 | False BLOCK /75 |
|---|---|---|---|
| argmax (`strict`) | 0 | **0** | 27 |
| argmax | 0.9 | 2 | 19 |
| argmax | 0.99 | 3 | 13 |
| 0.1 | 0 | 0 | 31 |
| 0.05 (`maximum`) | 0 | 0 | 32 |

* **`strict` is the recommended default.** It is the only point with zero observed leaks that does not add false blocks. Every precision knob trades leaks for usability.
* **`maximum` stays available.** On `dev_v1` it adds 5 false blocks with no measurable leak benefit, but on synthetic report-only sets it halves leakage: format shift 45 → 20; `test_long` 2 → 0.
* No threshold was tuned on `challenge_v1`.
* `configs/inference/policy.json` now carries this evidence; the default is unchanged (`strict`).

## 9. Decision F (out-of-scope API keys) in the evaluation

* `challenge_v1` annotates its only API key (`code-013`, an AWS secret access key) as `~SECRET` (ignored).
* A second overlay version (`data/challenge/challenge_v1_overlay_final_policy_v2.json`, operation `ignore_to_negative`) turns it into an out-of-scope `APIKEY` look-alike, producing `challenge_v1_final`. The frozen file and `challenge_v1_policy` are unchanged.
* Predictions were reused only because the texts are byte-identical (`scripts/retarget_predictions.py`). They are stored separately in `results/round2_derived/`.

`challenge_v1_final` (95 BLOCK / 57 ALLOW), system/strict, False ALLOW / False BLOCK:

| R0 | R1 | R2 | R3 | R4 |
|---|---|---|---|---|
| 2 / **9** | 2 / **9** | 6 / **2** | 2 / 7 | 2 / 4 |

* R0–R2 call the key PASSWORD and are now charged one entity false positive and one False BLOCK.
* R3 and R4 do not flag it in `strict` mode; R3 does in `maximum`.
* `dev_v1` contains no API-key case, so decision F does not change the selection. It is essentially unmeasured in the hand-written data, which is why `challenge_v2` now requires an `oos-secret` tag.

## 10. Recommended configuration

| Component | Setting |
|---|---|
| Model | `r2_e3b_positive` (R3): mBERT-cased, label policy v3, format-A augmentation, + `B_train`. Drive: `MyDrive/confidentiality_detector/round2/checkpoints/r2_e3b_positive` |
| Rules | rules v3 (`detectors/rules.py`, `RULES_VERSION = "v3"`) |
| Reconciliation | `hybrid.merge`, with rule priority for EMAIL, IPV4, IBAN, card number and SSN |
| Policy | `configs/inference/policy.json`: 13 blocking labels; fail-closed on error and oversize (decision D, confirmed); default mode `strict`; `maximum` optional |
| Inference windows | 512 tokens, 64 overlap, `"first"` stitching (as evaluated; `inference` section of `policy.json`), unless the window study adopts centered stitching or a shorter window under its pre-registered rule (`docs/METHODOLOGY.md` §7) |

This is the simplest defensible system. It uses the same backbone, recipe and pipeline as Round 1, with one extra data file. It is not production-ready:
* every number comes from synthetic or author-written text;
* `dev_v1` has 56 / 75 documents;
* no real prompts were evaluated (`docs/RISKS.md`).

## 11. Remaining issues

| Severity | Issue | Evidence | Remedy |
|---|---|---|---|
| High (usability) | False blocks on harmless identifiers | `dev_v1` 36%; held-out hard-negative families 69%; high-confidence model errors | Data, not thresholds. R4's recipe works on false blocks but leaks more on unseen formats. A future round would need a pre-registered rebalanced hard-negative set and a **new** development set (`dev_v1` has now served one selection). |
| Medium (security) | Long inputs: no right context before window cuts, and positions ≥ 128 are untrained | §3; R3 `test_long` FA 2/45, FB 5/28 | CPU-only first: `scripts/window_study.py` (centered stitching and shorter windows; rule fixed in `docs/METHODOLOGY.md` §7; chosen on `validation_long` and `dev_v1`). If insufficient: packed multi-document training windows (GPU, one factor). |
| Medium (evidence) | Small hand-written sets; author-written | `dev_v1` CI for R3 False ALLOW 0–6.4% | `challenge_v2` (independent), then governed real prompts |
| Low | `synth_B_heldout` shares 20% of values with `B_train` | §2 | Hold out value pools as well as families in any future generator round |
| Low | Out-of-scope keys essentially unmeasured | 1 case | `challenge_v2` `oos-secret` tag |
| Low | Scheduler ran ahead on AMP-skipped steps | §4 | Fixed for future runs; no effect on comparisons |
| Info | One seed per configuration | — | ≥ 3 seeds for the final configuration before any deployment claim |

## 12. Is further GPU training needed?

**Not for the delivery candidate.**
* The pre-registered process has produced a selected system that improves security over Round 1 without in-distribution regression.
* Further rounds would be justified only by a product decision that the false-block level is unacceptable. That round would need its own pre-registration and a fresh development set.
* The long-input weakness should first be tested with the inference-only window study, which needs no GPU and no retraining. The stitching flaw in particular is an inference defect that retraining would not fix.
* No backbone change is indicated: the errors are coverage and position effects, and in-distribution F1 is about 0.985.

## 13. Readiness for `challenge_v2`

| Requirement | Status |
|---|---|
| 13-label policy | target labels outside the 13 are a parse error; the policy config rejects out-of-scope blocking labels |
| Offsets and spans | spans computed by the parser (never hand-written); bounds, overlap and whitespace checks; decision consistency (BLOCK ⇔ ≥ 1 target) |
| Data fingerprint | `seal` records the sha256; `evaluate` refuses unsealed or modified files |
| System fingerprint | **new:** `freeze` records weights sha256, policy sha256, rules version and window settings (max length, overlap, stitching, read from `policy.json`) in `configs/inference/frozen_system.json` (optionally after verifying the local checkpoint reproduces its stored `dev_v1` predictions); `evaluate` refuses any other system |
| Prediction fingerprint | **new:** the ledger records a sha256 over ids, decisions, positions and labels (no text) |
| Entity and document metrics | per-class P/R/F1, error taxonomy, False ALLOW/BLOCK with Wilson CIs, three success levels, per tag |
| Out-of-scope false positives | look-alikes (`!TYPE`) count as `hard_negative` false positives and False BLOCKs; **new:** `~SECRET`/`~APIKEY`/`~TOKEN`… is a validation error (decision F); `oos-secret` coverage tag |
| Long documents | `long` tag (≥ ~500 words), plus a **new** per-length breakdown (≤ 1,000 / 1,001–3,000 / > 3,000 characters) |
| No exposure of values | all outputs aggregate; case details (ids, tags, categories) only for the author, on request |

The interface is ready, but the system is not frozen yet. Remaining steps (CPU, local):

1. Download `round2/checkpoints/r2_e3b_positive/` from Drive to `checkpoints/r2_e3b_positive/`. This is git-ignored; never commit weights.
2. Recommended: `python scripts/window_study.py --model-dir checkpoints/r2_e3b_positive`. If it adopts a candidate, set the `inference` section of `configs/inference/policy.json` accordingly.
   * With `"first"` stitching and 512/64, the freeze verification below reproduces the stored predictions exactly.
   * With another setting, the 2 long `dev_v1` documents can differ, and verification will report them; freeze without `--verify-pred-dir` in that case, after confirming the checkpoint once with the default setting.
3. Run:
   ```
   python scripts/challenge_v2.py freeze --model-dir checkpoints/r2_e3b_positive --verify-pred-dir results/round2/predictions/r2_e3b_positive
   ```
4. Hand `docs/CHALLENGE_V2_SPEC.md` and `docs/CASE_FORMAT.md` to the independent author.

## 14. Changes made during this analysis

| Area | Change | Tests |
|---|---|---|
| Training loop | `train.optimizer_step`: scheduler advances only after real updates; skipped steps and learning rate are logged | `tests/test_training_loop.py` (2) |
| Model-input guards | `encode_text(verbose=False)`; explicit max-length checks in `training_features`, `wrap_window` and `TransformerDetector` | `test_end_to_end_with_saved_checkpoint_long_document` (forward hook ≤ 512; limit check) |
| Window stitching | `inference_windows(stitching="centered")` and `Window.owned`; the window settings move into the `inference` section of `policy.json`, which `ConfidentialityDetector.load` uses. The default (`"first"`, 512/64) is the evaluated behaviour, unchanged | `test_centered_stitching_gives_context_on_both_sides` (7 cases); pipeline test |
| Decision F | `apply_overlay` gains `ignore_to_negative`; overlay v2; derived set `challenge_v1_final`; `challenge_v2` validator rejects `~` on out-of-scope credentials | 3 tests in `tests/test_challenge_v2.py` |
| `challenge_v2` | `freeze` / frozen-system check, prediction fingerprint, per-length metrics, `oos-secret` tag | 2 tests |
| Fail-closed (D) | explanation wording checked (no category, no detection claim) | `test_fail_closed_on_error_oversize_and_empty` |
| Evaluation sets | `validation_long` (79 documents, selection set for inference settings) and `challenge_v1_final` added. The other 13 sets rebuild **byte-identically**; the Round 2 manifest is kept as `data/eval_v3/manifest_round2.json` | — |
| Analysis scripts | `verify_round2.py`, `analyze_long_docs.py`, `evaluate_system.py`, `window_study.py` | smoke-run |
| Docs | `POLICY.md` (D confirmed, F, mode evidence), `METHODOLOGY.md` (outcome, levels, §7 window rule), `RISKS.md`, `CHALLENGE_V2_SPEC.md`, `CASE_FORMAT.md`, `ANNOTATION_GUIDELINES.md`, `data/challenge/README.md`, `ROUND2_PLAN.md` (status), `configs/inference/policy.json` (evidence text) | — |

* Test suite: 125 passed locally.
* Nothing in `results/round1`, `results/round2`, the checkpoints or the frozen case files was modified.

## 15. Reproduce

```
python scripts/verify_round2.py --results results/round2
python scripts/analyze_round2.py --results results/round2
python scripts/evaluate_system.py --results results/round2
python scripts/analyze_long_docs.py --results results/round2
python scripts/operating_points.py --pred r2_e3b_positive --pred-root results/round2/predictions --rules rules_v3 --set dev_v1
python scripts/calibration.py --pred r2_e3b_positive --pred-root results/round2/predictions --eval-dir data/eval_v3 --sets dev_v1 synth_A_heldout synth_B_heldout test
python scripts/evaluate_system.py --results results/round2_derived --rules-root results/round2_derived/rules --sets challenge_v1_final --out reports/round2_system_eval_challenge_v1_final.json
```
