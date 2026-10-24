# Confidentiality Detector — Investigation Report

**Status: interim (round 0).** Every number below comes from a command that was actually run on the local machine. Anything that needs the existing checkpoint or GPU training is listed as **pending (Colab round 1)**, and nothing has been concluded from it yet.

Legend: **[F]** observed fact (with the command that reproduces it) · **[H]** hypothesis still to be tested · **[D]** decision with rationale.

---

## 1. Pipeline as found

```
data/raw/english_pii_43k.jsonl   English slice of ai4privacy/pii-masking-200k (43,501 records, 56 labels)
   └─ notebooks/02_mbert_dataset_splitting      random 80/10/10 per record (seed 42) + exact-template dedup (moved 3 records)
       └─ notebooks/03_..._alignment            char spans -> mBERT subword BIO2 (27 labels), 512-token windows, overlap 32
           └─ notebooks/04_mbert_finetuning     HF Trainer on Colab, seqeval strict IOB2 on windows, best = checkpoint-4352
```

* [F] Every `.py` module was empty (`src/detectors/mbert_detector.py`, `src/training/bio_alignment.py`, `evaluation/metrics.py`). The whole pipeline lived in notebooks.
* [F] No BLOCK/ALLOW decision logic, Presidio baseline, inference code or test-set evaluation existed. `README.md` and `scope.md` describe an earlier Arabic/regex scope.
* [F] The trained checkpoint exists only on Google Drive. The local `mbert_ner` is a 0-byte file.
* [F] Local compute is CPU-only (i7-1260P, 16 GB). Training DistilBERT locally takes about 1.6 s per batch of 16, roughly 1 h per epoch, so all fine-tuning goes to Colab.

## 2. Root-cause analysis of the 0.9925 validation F1

### 2.1 The metric could not see most false positives (primary defect)

* [F] The original `build_bio2_labels` assigns `-100` (ignore) to **every token of every non-target entity**. `compute_metrics` then maps `-100 → O` in **both** gold and prediction. Any prediction on those tokens is therefore erased before scoring.
* [F] On the validation split this covers **31.0% of all tokens** and **9,172 non-target entity spans, about twice the 4,667 target entities**. These include look-alikes such as IPV6 (240), PHONEIMEI (186), PIN (64), BIC (71), MAC (107), VEHICLEVIN (90), crypto addresses (536) and dates (479). (`scripts/audit_dataset.py`, `reports/dataset_audit.json`)
* [F] Unit test `test_original_metric_hides_false_positives_on_ignored_positions` shows the mechanism: a CVV predicted on a PIN gives precision 1.0 under the original metric and 0.5 under the corrected one.
* [F] The same tokens also carry no training loss, so the model never learned that these values are *not* targets.
* [H] Reported precision (0.991) is inflated by an unknown amount, because false positives on out-of-scope look-alikes were invisible. **Pending:** `reproduce_original_metric.py` rows A→D on the real checkpoint quantify this.

### 2.2 Label noise and ambiguity in the source data

* [F] **47.9% of `IP` entities are IPv4 addresses**, yet `IP` sits outside the target set, so they were ignored. By the task definition they are IPV4.
* [F] **`MASKEDNUMBER` values are 100% full, unmasked 16-digit numbers**, surface-identical to card numbers, and 22% follow card cues ("card ending in …").
* [F] `MIDDLENAME` is often used for standalone given names ("guidance of [PREFIX] [MIDDLENAME]").
* [D] Label policy **v2** (`src/confidentiality_detector/labels.py`):
  * `IP` with an IPv4 value → `IPV4`.
  * `MIDDLENAME` and `MASKEDNUMBER` → **ignore**: they're ambiguous, so they're neither trained nor scored, and documents whose only annotations are these are excluded from document-level metrics.
  * Every other non-target entity → **`O`**, so it is trained as a hard negative and scored.
  * Ignored-token share on validation falls from 31.0% to 1.0%.

### 2.3 Leakage: checked, mostly *not* the problem

* [F] Exact or normalised duplicate texts across splits: **0**. Shared placeholder templates: **0** after the notebook's move step.
* [F] Near-duplicate templates (TF-IDF 1–3-gram cosine on placeholder text): median max-similarity to train is 0.19. Only **0.7–0.8%** of validation/test docs reach ≥ 0.5, and 0.05% reach ≥ 0.9.
* [F] Windows are created after splitting, and overlap positions are labelled `-100` in the later window, so no entity is counted twice. Only 2 validation records exceed 510 tokens.
* Conclusion: split leakage is not what drives the score.

### 2.4 The synthetic data is easy in ways real text is not

* [F] **Explicit cues:** 63% of validation target entities have a two-word left context that already precedes the same label in train ("account number", "ip address", "password is", "dear").
* [F] **Value reuse:** 50% of validation target values occur verbatim in train. For first and last names it is 96–98%; CVV 58%, STREET 33%, USERNAME 21%.
* [F] **Unrealistic formats:**
  * Every CREDITCARDNUMBER is 16 bare digits, with no spaces or dashes, and only **10.3% pass the Luhn check**.
  * 51% of SSNs have 11 digits.
  * Every ACCOUNTNUMBER is 8 digits and every CVV is 3 digits.
  * Only 9% of phone numbers parse as real numbers.
  * Usernames and emails are almost entirely Faker-style `Firstname99` / `Firstname.Lastname@domain.tld`.
* [F] There are **no clean documents**: every record contains some PII. ALLOW behaviour can only be tested on records whose PII is entirely out of scope (1,325 validation docs under v2), plus the hand-written challenge set.
* [F] Long documents are essentially absent (max test length 170 tokens), so windowing was never exercised in evaluation.
* [H] The model may rely on cue words and value memorisation, and may not generalise to cue-less text, unseen formats or names. **Pending:** the `test_unseen_context`, `test_unseen_value`, `test_format_shift` and `challenge_v1` results.

### 2.5 Training-code defect

* [F] `load_best_model_at_end=True` in Transformers 5.20.1 logged *"missing keys in the checkpoint model loaded: …LayerNorm.weight/bias"*, because the checkpoint stores `gamma/beta`. The in-memory `trainer.model` after `train()` therefore had re-initialised LayerNorms. The logged per-epoch metrics are unaffected, since they were computed before the reload. `from_pretrained` loads the files correctly, as you verified.
* [D] The new training loop (`scripts/train.py`) never restores weights in memory. It selects the best epoch, **reloads it from disk, and fails if the reloaded validation score differs**.

## 3. Evaluation protocol (new)

| Set | Built from | Purpose | n docs |
|---|---|---|---|
| `validation` | original validation split | model selection and thresholds **only** | 4,350 |
| `test` | original test split (untouched by checkpoint-4352 training and selection) | in-distribution synthetic | 4,349 |
| `test_unseen_context` | test entities whose 2-word left context never precedes that label in train | cue memorisation (recall) | 1,466 |
| `test_unseen_value` | test entities whose exact value never occurs in train | value memorisation (recall) | 1,933 |
| `test_novel_template` / `test_familiar_template` | test docs with max template similarity < 0.15 / ≥ 0.35 | template generalisation | 869 / 159 |
| `test_format_shift` | test docs with values re-rendered in **format family B** (never used for training) | held-out generation patterns | 3,062 |
| `test_long` | 597–942-token concatenations; one PII doc hidden among out-of-scope docs | windowing, long inputs | 73 |
| `challenge_v1` | **154 hand-written cases**, frozen by SHA-256 before any model was scored | realistic, independent | 154 (92 BLOCK / 60 ALLOW / 2 ambiguous) |

Metrics (`src/confidentiality_detector/metrics.py`):
* **Entities:** strict P/R/F1 on character spans at document level, plus per-class P/R/F1/support/TP/FP/FN.
* **"Caught (any type)" recall:** a target is caught if any prediction overlaps it. This is what matters for leakage.
* **Error taxonomy:** boundary, type confusion, missed, hard-negative FP (by out-of-scope label), spurious FP.
* **Documents:** BLOCK precision/recall, **False ALLOW Rate** (leaked docs / BLOCK docs) and False BLOCK Rate, both with Wilson 95% CIs, plus the confusion matrix.
* Reports contain character-class shapes (`Aa99`) and never raw values.

Protocol discipline:
* The challenge set (`data/challenge/challenge_v1.txt`, sha256 `c19cd914…`) and the eval-set hashes (`data/eval/manifest.json`) are fixed.
* Thresholds and rule changes are chosen on `validation` only.
* **Disclosure:** I looked at `test` and `challenge_v1` per-class output for `rules_v1` once, before switching to validation-only tuning. `rules_v2` changes were motivated solely by validation errors, and `rules_v1` remains reported as-is.

## 4. Baselines run so far (local CPU)

Document-level FAR = False ALLOW Rate (lower is safer); FBR = False BLOCK Rate.

| Detector | Set | Entity P | Entity R | Entity F1 | Caught | FAR | FBR |
|---|---|---:|---:|---:|---:|---:|---:|
| rules_v2 | test | 0.985 | 0.322 | 0.485 | 0.323 | 0.544 | 0.002 |
| rules_v2 | test_format_shift | 0.965 | 0.379 | 0.544 | 0.390 | 0.471 | — |
| rules_v2 | challenge_v1 | 0.978 | 0.472 | 0.636 | 0.477 | 0.283 | 0.017 |
| Presidio (en_core_web_lg, min score 0.3) | test | 0.632 | 0.539 | 0.582 | 0.656 | 0.216 | 0.153 |
| Presidio | test_format_shift | 0.691 | 0.545 | 0.610 | 0.658 | 0.218 | — |
| Presidio | test_long | 0.142 | 0.580 | 0.229 | 0.768 | 0.000 | 0.964 |
| Presidio | challenge_v1 | 0.803 | 0.653 | 0.720 | 0.710 | 0.217 | 0.117 |

* **Rules** are precise for structured identifiers but blind to names and street names. On the synthetic test their recall is also capped by the unrealistic values (90% of cards fail Luhn).
* **Presidio** has no PASSWORD, USERNAME, CVV or STREET recogniser, and its PERSON recogniser fires on out-of-scope names. That makes it block almost every long ALLOW document.
* Latency on this laptop: rules < 0.3 ms/doc, Presidio ≈ 9–10 ms/doc.

## 5. Colab round 1 — **completed; results in `reports/ROUND1_REPORT.md`**

Summary:
* Original 0.9925 reproduced; corrected validation F1 0.643 (precision 0.476).
* E1 fixes synthetic precision but leaks more on realistic text.
* E2 (format augmentation) generalises.
* Recommended system: E2 + rules_v2 (challenge FAR 2.2%, FBR 18.3%).

Round 2, which applies the final product policy and runs data-centric experiments, is described in `reports/ROUND2_PLAN.md`; the methodology is in `docs/`. The original round-1 plan follows for reference.

> **Attempt 1 failed in setup and produced no valid results.** seqeval's legacy sdist build aborted the pip install. See `reports/COLAB_ROUND1_FIX.md`. Its `round1/` folder on Drive is excluded from all comparisons. Re-run with bundle `round1-r2` into `round1_rerun/`; the methodology is unchanged.

| Step | Experiment | Single variable changed | Question answered |
|---|---|---|---|
| A | checkpoint-4352, metric rows A–D + all eval sets | evaluation only | How much of 0.9925 survives corrected scoring? How does it do OOD and on hard negatives? |
| B | **E1** `e1_mbert_v2` | label policy v1 → v2 | Does supervising out-of-scope entities as `O` fix hard-negative FPs without hurting recall? |
| C | **E2** `e2_mbert_v2_fmtA` | + format-family-A augmentation | Does format diversity transfer to the held-out family B and to the challenge set? |

Architecture decisions are deferred until these results exist. Planned once results are in, all local with no GPU:
* hybrid (best model + `rules_v2`);
* an operating-point sweep on validation (token threshold);
* failure analysis and latency on CPU.

## 6. Reproducibility

```bash
uv sync                                   # local env (Python 3.13); adds seqeval
python scripts/audit_dataset.py           # reports/dataset_audit.json
python scripts/build_eval_sets.py         # data/splits/original/*.ids, data/eval/*.jsonl, manifest.json
python -m pytest -q                       # 40 tests incl. exact reproduction of the original tokenised dataset
python scripts/predict.py --detector rules --name rules_v2
python scripts/predict.py --detector presidio --name presidio --presidio-threshold 0.0
python scripts/evaluate.py --pred rules_v2
python scripts/evaluate.py --pred presidio --tag s0.3 --min-score 0.3
python scripts/make_colab_bundle.py       # dist/colab_bundle.zip for Colab
```
