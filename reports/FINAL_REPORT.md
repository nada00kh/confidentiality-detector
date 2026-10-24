# Final report: Confidentiality Detector

> **Status: in progress.** Sections 1–4 describe the selected system and its development-time evidence, verified on 2026-10-24. The independent benchmark (`challenge_v2`), the development history and the final conclusions are added after the system is frozen (Step 9). **Nothing in this version is independent or real-world evidence.**

## 1. The system evaluated

| Component | Setting |
|---|---|
| Model | R3 `r2_e3b_positive`: mBERT-cased fine-tuned for 27 BIO labels (13 categories); `model.safetensors` sha256 `dc0fdca5…` (`reports/ARTIFACTS.md`) |
| Rules | rules v3 (`detectors/rules.py`): validators and context cues, reconciled with the model by `hybrid.merge` |
| Mode | `strict` (argmax decoding; any finding blocks). `maximum` is reported for reference only. |
| Inference windows | 512 tokens, 64 overlap, `first` stitching (kept by the window study, `docs/METHODOLOGY.md` §7) |
| Post-processing | none. The IPv4 validation gate was rejected and its code removed (§8). |
| Policy | `configs/inference/policy.json`: 13 labels, fail closed on errors and inputs over 100,000 characters, explanations without values |

**Checkpoint identity.** Re-run locally on CPU, the checkpoint reproduces **all 18,425 archived Round 2 predictions** on 13 evaluation sets: identical spans, token probabilities within 2.2e-5 (`reports/evidence/checkpoint_verification_r2_e3b_positive.json`).

**How the numbers were produced.** `scripts/evaluate_system.py --detail` writes `reports/evidence/final_system_metrics_r3.json`.
* The archived token probabilities, which are identical to the local re-run, go through the real pipeline: decoding, **live** rules v3, reconciliation and the security policy.
* `validation_long` has no Colab prediction, so it was predicted locally.
* Stored and live rule outputs agree on every document, and the model + rules ("hybrid") level agrees exactly with the full system in `strict` mode on every set.

## 2. Definitions

**Entity level.** Gold and predicted entities are character spans `(start, end, label)` on the whole document; sliding windows never enter the score.
* **Exact:** start, end and label must all match.
* **Relaxed:** the same label and any overlap. It credits boundary errors, never type errors.
* **Micro:** counts are pooled over labels; all P/R/F1 columns are micro. **Macro F1** is the unweighted mean of per-label exact F1 over the labels present in the set.
* **Ignore spans:** predictions inside ignore spans (ambiguous source annotations such as MIDDLENAME, or a CVV without evidence) count neither way.
* **Out-of-scope predictions** (for example on a PIN, IMEI or API key) **are false positives**.

**Document level.**
* **Classes:** BLOCK is the positive class; documents marked ambiguous, or whose only annotations are ignore spans, are excluded, and their number is shown.
* **Rates:** False ALLOW = gold BLOCK, predicted ALLOW (rate over gold BLOCK documents); False BLOCK = the reverse (rate over gold ALLOW documents). The 95% intervals are Wilson intervals.
* **Single-class sets:** where a set has only BLOCK or only ALLOW documents, document F1 is not meaningful and only the applicable error rate is given.

## 3. Results: R3 + rules v3, `strict`

### 3.1 Entity extraction (exact spans unless stated)

| Set | TP | FP | FN | Precision | Recall | **F1** | Macro F1 | Relaxed P | Relaxed R | Relaxed F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| *Original ai4privacy splits (synthetic, label policy v3)* | | | | | | | | | | |
| `validation` | 4,695 | 74 | 57 | 0.984 | 0.988 | **0.986** | 0.991 | 0.990 | 0.994 | 0.992 |
| `test` | 4,632 | 87 | 63 | 0.982 | 0.987 | **0.984** | 0.988 | 0.988 | 0.993 | 0.991 |
| *Subsets of `test`* | | | | | | | | | | |
| `test_unseen_value` | 2,341 | 20 | 7 | 0.992 | 0.997 | **0.994** | 0.983 | 0.993 | 0.998 | 0.996 |
| `test_unseen_context` | 1,820 | 44 | 37 | 0.976 | 0.980 | **0.978** | 0.982 | 0.984 | 0.988 | 0.986 |
| `test_novel_template` | 791 | 20 | 16 | 0.975 | 0.980 | **0.978** | 0.988 | 0.985 | 0.989 | 0.987 |
| `test_familiar_template` | 182 | 1 | 1 | 0.995 | 0.995 | **0.995** | 0.997 | 0.995 | 0.995 | 0.995 |
| *Long documents (synthetic concatenations)* | | | | | | | | | | |
| `validation_long` | 76 | 7 | 0 | 0.916 | 1.000 | **0.956** | 0.956 | 0.916 | 1.000 | 0.956 |
| `test_long` | 64 | 18 | 2 | 0.780 | 0.970 | **0.865** | 0.890 | 0.780 | 0.970 | 0.865 |
| *Synthetic stress sets* | | | | | | | | | | |
| `test_format_shift` | 3,769 | 911 | 926 | 0.805 | 0.803 | **0.804** | 0.813 | 0.848 | 0.843 | 0.846 |
| `synth_B_heldout` | 1,295 | 248 | 183 | 0.839 | 0.876 | **0.857** | 0.851 | 0.889 | 0.921 | 0.904 |
| `synth_A_heldout` | 0 | 871 | 0 | — | — | — | — | — | — | — |
| *Hand-written (not independent)* | | | | | | | | | | |
| `dev_v1` | 76 | 60 | 10 | 0.559 | 0.884 | **0.685** | 0.693 | 0.588 | 0.930 | 0.721 |
| `challenge_v1_final` | 171 | 42 | 28 | 0.803 | 0.859 | **0.830** | 0.844 | 0.850 | 0.894 | 0.872 |

### 3.2 BLOCK/ALLOW decisions

| Set | BLOCK docs | ALLOW docs | Ambiguous (excluded) | False ALLOW (rate; 95% CI) | False BLOCK (rate; 95% CI) | BLOCK P | BLOCK R | **BLOCK F1** | ALLOW P | ALLOW R | ALLOW F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| *Original ai4privacy splits (synthetic, label policy v3)* | | | | | | | | | | | |
| `validation` | 3,017 | 1,154 | 179 | 4/3,017 (0.1%; 0.1%–0.3%) | 9/1,154 (0.8%; 0.4%–1.5%) | 0.997 | 0.999 | **0.998** | 0.997 | 0.992 | 0.994 |
| `test` | 3,055 | 1,068 | 226 | 3/3,055 (0.1%; 0.0%–0.3%) | 11/1,068 (1.0%; 0.6%–1.8%) | 0.996 | 0.999 | **0.998** | 0.997 | 0.990 | 0.993 |
| *Subsets of `test`* | | | | | | | | | | | |
| `test_unseen_value` | 1,931 | 0 | 0 | 0/1,931 (0.0%; 0.0%–0.2%) | — | — | — | — | — | — | — |
| `test_unseen_context` | 1,460 | 0 | 0 | 2/1,460 (0.1%; 0.0%–0.5%) | — | — | — | — | — | — | — |
| `test_novel_template` | 542 | 277 | 50 | 1/542 (0.2%; 0.0%–1.0%) | 2/277 (0.7%; 0.2%–2.6%) | 0.996 | 0.998 | **0.997** | 0.996 | 0.993 | 0.995 |
| `test_familiar_template` | 116 | 35 | 8 | 0/116 (0.0%; 0.0%–3.2%) | 0/35 (0.0%; 0.0%–9.9%) | 1.000 | 1.000 | **1.000** | 1.000 | 1.000 | 1.000 |
| *Long documents (synthetic concatenations)* | | | | | | | | | | | |
| `validation_long` | 49 | 30 | 0 | 0/49 (0.0%; 0.0%–7.3%) | 2/30 (6.7%; 1.8%–21.3%) | 0.961 | 1.000 | **0.980** | 1.000 | 0.933 | 0.966 |
| `test_long` | 45 | 28 | 0 | 2/45 (4.4%; 1.2%–14.8%) | 5/28 (17.9%; 7.9%–35.6%) | 0.896 | 0.956 | **0.925** | 0.920 | 0.821 | 0.868 |
| *Synthetic stress sets* | | | | | | | | | | | |
| `test_format_shift` | 3,055 | 0 | 0 | 45/3,055 (1.5%; 1.1%–2.0%) | — | — | — | — | — | — | — |
| `synth_B_heldout` | 776 | 0 | 0 | 0/776 (0.0%; 0.0%–0.5%) | — | — | — | — | — | — | — |
| `synth_A_heldout` | 0 | 960 | 0 | — | 664/960 (69.2%; 66.2%–72.0%) | — | — | — | — | — | — |
| *Hand-written (not independent)* | | | | | | | | | | | |
| `dev_v1` | 56 | 75 | 4 | 0/56 (0.0%; 0.0%–6.4%) | 27/75 (36.0%; 26.1%–47.3%) | 0.675 | 1.000 | **0.806** | 1.000 | 0.640 | 0.780 |
| `challenge_v1_final` | 95 | 57 | 2 | 2/95 (2.1%; 0.6%–7.4%) | 7/57 (12.3%; 6.1%–23.2%) | 0.930 | 0.979 | **0.954** | 0.962 | 0.877 | 0.917 |

### 3.3 Diagnostic: the transformer alone (argmax, no rules)

Not the product. This shows what the rules add.

| Set | Model-only exact F1 | Model-only relaxed F1 | Model-only False ALLOW | Model-only False BLOCK | System exact F1 (for comparison) |
|---|---|---|---|---|---|
| `validation` | 0.986 | 0.992 | 4/3,017 | 7/1,154 | 0.986 |
| `test` | 0.985 | 0.992 | 3/3,055 | 10/1,068 | 0.984 |
| `test_unseen_value` | 0.996 | 0.997 | 0/1,931 | 0/0 | 0.994 |
| `test_unseen_context` | 0.980 | 0.988 | 2/1,460 | 0/0 | 0.978 |
| `test_novel_template` | 0.979 | 0.988 | 1/542 | 1/277 | 0.978 |
| `test_familiar_template` | 0.995 | 0.995 | 0/116 | 0/35 | 0.995 |
| `validation_long` | 0.962 | 0.962 | 0/49 | 2/30 | 0.956 |
| `test_long` | 0.877 | 0.877 | 2/45 | 5/28 | 0.865 |
| `test_format_shift` | 0.746 | 0.826 | 46/3,055 | 0/0 | 0.804 |
| `synth_B_heldout` | 0.833 | 0.896 | 2/776 | 0/0 | 0.857 |
| `synth_A_heldout` | — | — | 0/0 | 664/960 | — |
| `dev_v1` | 0.649 | 0.694 | 0/56 | 27/75 | 0.685 |
| `challenge_v1_final` | 0.793 | 0.845 | 4/95 | 7/57 | 0.830 |

### 3.4 Reference: `maximum` mode

False ALLOW / False BLOCK, compared with `strict`:

| Set | `maximum` | `strict` |
|---|---|---|
| `validation` | 1 / 13 | 4 / 9 |
| `test` | 2 / 17 | 3 / 11 |
| `dev_v1` | 0 / 32 | 0 / 27 |
| `test_long` | 0 / 6 | 2 / 5 |
| `test_format_shift` | 20 / — | 45 / — |
| `challenge_v1_final` | 0 / 11 | 2 / 7 |

## 4. What these numbers support, and what they do not

* **On the original ai4privacy test split, R3 + rules v3 has an exact-span entity F1 of 0.984** (P 0.982, R 0.987; 4,632 TP, 87 FP, 63 FN). **Its BLOCK/ALLOW F1 is 0.998**, with False ALLOW 3/3,055 (0.1%) and False BLOCK 11/1,068 (1.0%).
  * This is **synthetic, template-generated, in-distribution** data.
  * Target values repeat heavily across splits (`docs/DATA_PIPELINE.md` §0).
  * `test` also served as a non-inferiority gate in the Round 2 selection.
  * It shows the model learned the source distribution. It does not show real-world performance.
* **On realistic hand-written prompts the same system scores much lower.**
  * `dev_v1`: entity F1 0.685, BLOCK F1 0.806. It allows no protected document (0/56, upper bound 6.4%) but blocks 27 of 75 harmless prompts. All 27 are cases tagged `hardneg` (deliberately constructed look-alikes); none of its 10 cases tagged `clean` is blocked (case tags in `data/dev/dev_v1.txt`; ids in the evidence file).
  * `dev_v1` chose this model, so these numbers are, if anything, optimistic.
  * `challenge_v1_final` (entity F1 0.830, BLOCK F1 0.954, False ALLOW 2/95) was studied during development and is regression evidence only.
* **The gap between about 0.98 (synthetic) and 0.69–0.83 (hand-written) is the most important measured fact.** Synthetic in-distribution scores overstate quality on realistic text, mainly through false positives on look-alike identifiers. Entity precision on `dev_v1` is 0.559, against recall 0.884.
* **Robustness, all synthetic:**
  * new value formats leak 1.5% of documents (`test_format_shift`, 45/3,055);
  * long documents leak 2/45 and over-block 5/28 (`test_long`);
  * harmless look-alike identifiers from held-out generator families are blocked 69% of the time (`synth_A_heldout`).
* **No set is pooled with another**, and no number here is independent. The independent number will come from `challenge_v2`, evaluated once after the freeze. There is no real-world validation.

## 5. Data provenance and experiment lineage

See `docs/DATA_PIPELINE.md` §0. In short:
* The data is the English subset (43,501 records) of `ai4privacy/pii-masking-200k`, on the original 34,802 / 4,350 / 4,349 split, which was kept unchanged throughout.
* The labels were corrected by policy v3.
* R3 was trained on 49,685 documents: 34,802 original training documents, 12,196 format-A augmented copies and 2,687 synthetic difficult positives (`B_train`). Its epoch was selected on validation entity F1.

## 6. To be completed after the freeze (Step 9)

* the frozen-system fingerprint and the single `challenge_v2` evaluation;
* the development history: original notebooks, the misleading 0.9925, corrected labelling and evaluation, Rounds 1 and 2, selection, the long-document and inference studies;
* limitations and future work (currently in `docs/RISKS.md`);
* the model card and the demonstration.
