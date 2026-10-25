# Final report: Confidentiality Detector

> **Status: final (2026-10-25).**
> * Sections 1–4: the frozen system and its development-time evidence.
> * Section 5: the **independent benchmark `challenge_v2`**, evaluated once per mode after the freeze. It is the only independent evidence.
> * Sections 6–10: the mode decision, the development history, data provenance, a model card and the limitations.
>
> **No result in this report comes from real employee prompts.** The detector is a research prototype, **not production-ready**.

## 1. The system evaluated

| Component | Setting |
|---|---|
| Model | R3 `r2_e3b_positive`: mBERT-cased fine-tuned for 27 BIO labels (13 categories); `model.safetensors` sha256 `dc0fdca5…` (`reports/ARTIFACTS.md`) |
| Rules | rules v3 (`detectors/rules.py`): validators and context cues, reconciled with the model by `hybrid.merge` |
| Mode | **`strict`** (argmax decoding; any finding blocks): the primary mode and the one the application uses. `maximum` (token threshold 0.05) is a secondary, experimental mode: kept in the code and policy for reproducibility, never offered to users (§6). |
| Inference windows | 512 tokens, 64 overlap, `first` stitching (kept by the window study, `docs/METHODOLOGY.md` §7) |
| Post-processing | none. The IPv4 validation gate was rejected and its code removed (§8). |
| Policy | `configs/inference/policy.json`: 13 labels, fail closed on errors and inputs over 100,000 characters, explanations without values |
| Frozen | 2026-10-24, `configs/inference/frozen_system.json`: sha256 of every checkpoint file, the policy and the 12 inference-code files (rules included), the windows, the runtime versions, code commit `4907107`. Freezing re-verified the checkpoint and the live decisions in both modes against this report's evidence. |

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
* **No set is pooled with another**, and no number in §3–4 is independent. The independent result is §5. There is no real-world validation.

## 5. Independent benchmark: `challenge_v2`

### 5.1 Protocol, as executed

* **Author.** A separate author wrote and annotated the cases under `docs/CHALLENGE_V2_HANDOFF.md` (v1.0) and `docs/CHALLENGE_V2_SPEC.md`. The developers never saw the cases, the detector's output on them or any per-case result. Everything below comes from the four aggregate files in `reports/challenge_v2/`.
* **Before the data.** The system was frozen on 2026-10-24, at code commit `4907107`, as recorded in `configs/inference/frozen_system.json`. The evaluation tooling was then hardened without touching the detector (commit `c8300ec`). The hardening added strict case-file validation and per-look-alike-type reporting; `verify-frozen` passed before and after it.
* **Validation and seal.** The file passed validation and was sealed on 2026-10-25 17:38 (`SEAL.json`, sha256 `e3f7408185878e8a053eb8748f97c16c5da06b82859d9afda50a3320eb020f8c`).
* **Evaluation.** Each mode was evaluated **once**, in the pre-declared order: `strict` at 17:48 (primary), then `maximum` at 18:00 (secondary).
  * `LEDGER.jsonl` holds exactly these two entries. Both record the sealed sha256, the frozen identity (weights `dc0fdca5…`, rules v3, windows 512/64/first, code commit `4907107`) and the evaluator (commit `c8300ec`, no uncommitted changes).
  * Each entry also records a fingerprint of the predictions.
* **After the evaluation.** No change was made to the system in response to the results. A changed system would need a new independent set.
* **The shared files**, committed byte for byte as written (`.gitattributes`: `-text`):

  | File | sha256 |
  |---|---|
  | `reports/challenge_v2/SEAL.json` | `a4da23058798f12aef2b07a7fc9268d5e42a9a60f0773236af96feb8f18da786` |
  | `reports/challenge_v2/LEDGER.jsonl` | `74734d0bb8801693ea8a4be3dfb29dfc0a31e76dbe33a19cf7d9b4bb263528a7` |
  | `reports/challenge_v2/result_r2_e3b_positive_strict.json` | `4a5ce061cf2dd4af7f0436e3de12fbf8addf95da2ba615bde2be57f7669be2a3` |
  | `reports/challenge_v2/result_r2_e3b_positive_maximum.json` | `4831072bfc597202dd9b3e8b17ffc9ef2cd03d1cb6024f897841d448339d9ce9` |

### 5.2 The dataset (aggregates only)

* **Cases:** 400, of which 200 are BLOCK, 200 ALLOW and 0 AMBIGUOUS.
* **Target entities:** 236 across all 13 labels: FIRSTNAME and LASTNAME 31 each, PHONENUMBER and SSN 15 each, every other label 16.
* **Look-alikes:** 166 annotated spans of 25 types (`!TRACKING`, `!VERSION`, `!APIKEY`, …).
* **Tags:**
  * `structured` 171;
  * `lookalike` 152 (110 of them ALLOW);
  * `difficult-positive` 80 (all BLOCK);
  * `long` 72 (all over 3,000 characters);
  * `unfamiliar-format` 72;
  * `oos-secret` 21;
  * every case is also tagged `enterprise`.
* **Lengths:** 328 cases have at most 1,000 characters and 72 have more than 3,000; none falls in between.

### 5.3 Document level: BLOCK/ALLOW

| Metric | **`strict`** (primary) | `maximum` (secondary) |
|---|---:|---:|
| False ALLOW (gold BLOCK → ALLOW) | **2/200 = 1.0%** (95% CI 0.3–3.6%) | 1/200 = 0.5% (0.1–2.8%) |
| False BLOCK (gold ALLOW → BLOCK) | **70/200 = 35.0%** (28.7–41.8%) | 78/200 = 39.0% (32.5–45.9%) |
| BLOCK precision | 0.739 | 0.718 |
| BLOCK recall | 0.990 | 0.995 |
| **BLOCK F1** | **0.846** | 0.834 |
| Accuracy | 0.820 | 0.8025 |
| Confusion (TP / FN / FP / TN) | 198 / 2 / 70 / 130 | 199 / 1 / 78 / 122 |

### 5.4 Entity level (exact spans, micro)

| | **`strict`** | `maximum` |
|---|---:|---:|
| TP / FP / FN | 212 / 178 / 24 | 212 / 238 / 24 |
| Precision | 0.544 | 0.471 |
| Recall | 0.898 | 0.898 |
| **F1** | **0.677** | 0.618 |
| Overlap recall (same label, any overlap) | 0.919 | 0.924 |
| Gold entities overlapped by a finding of any type | 0.983 | 0.987 |
| BLOCK cases with every gold entity found | 0.980 | 0.985 |
| Missed entities (FN): type confusion / boundary / missed | 15 / 5 / 4 | 15 / 6 / 3 |
| False positives: on look-alikes / spurious / type confusion / boundary | 124 / 32 / 17 / 5 | 158 / 54 / 19 / 7 |

Per label, `strict`. F1 for `maximum` is in the last column.

| Label | Support | Precision | Recall | F1 | Any-type recall | F1 `maximum` |
|---|---:|---:|---:|---:|---:|---:|
| STREET | 16 | 1.000 | 1.000 | 1.000 | 1.00 | 0.970 |
| EMAIL | 16 | 0.941 | 1.000 | 0.970 | 1.00 | 0.914 |
| LASTNAME | 31 | 0.929 | 0.839 | 0.881 | 1.00 | 0.881 |
| FIRSTNAME | 31 | 0.871 | 0.871 | 0.871 | 1.00 | 0.871 |
| CREDITCARDNUMBER | 16 | 0.762 | 1.000 | 0.865 | 1.00 | 0.865 |
| CREDITCARDCVV | 16 | 0.762 | 1.000 | 0.865 | 1.00 | 0.711 |
| PHONENUMBER | 15 | 0.714 | 1.000 | 0.833 | 1.00 | 0.769 |
| IBAN | 16 | 0.516 | 1.000 | 0.681 | 1.00 | 0.471 |
| IPV4 | 16 | 0.500 | 0.938 | 0.652 | 0.94 | 0.625 |
| PASSWORD | 16 | 0.349 | 0.938 | 0.508 | 1.00 | 0.462 |
| SSN | 15 | 0.385 | 0.667 | 0.488 | 1.00 | 0.488 |
| ACCOUNTNUMBER | 16 | 0.254 | 1.000 | 0.405 | 1.00 | 0.390 |
| USERNAME | 16 | 0.190 | 0.500 | 0.276 | 0.81 | 0.222 |

### 5.5 Where the errors are

**False BLOCK is the dominant error, and it sits on look-alike identifiers.**
* In `strict`, 64 of the 70 false blocks are among the 110 ALLOW cases tagged `lookalike` (58%). The other 90 ALLOW cases have 6 (7%).
* 124 of the 178 entity false positives (70%) lie on annotated look-alikes.
* Per look-alike type (`lookalike_fp_by_type`, `strict`):

| Look-alike type | ALLOW cases with it | … blocked | False positives, predicted as |
|---|---:|---:|---|
| TRACKING | 5 | 5 | 36: ACCOUNTNUMBER 21, IBAN 15 |
| APIKEY | 5 | 4 | 19: PASSWORD 19 |
| VERSION | 5 | 5 | 14: IPV4 14 |
| SERIAL | 6 | 6 | 11: ACCOUNTNUMBER 6, PHONENUMBER 5 |
| ORDERID | 6 | 6 | 7: SSN 6, PHONENUMBER 1 |
| INVOICE | 6 | 6 | 6: SSN 6 |
| PRIVATEKEY | 5 | 5 | 6: ACCOUNTNUMBER 5, PASSWORD 1 |
| IMEI | 5 | 5 | 5: CREDITCARDNUMBER 5 |
| MEETINGID | 5 | 5 | 5: ACCOUNTNUMBER 5 |
| ROUTING | 5 | 5 | 5: ACCOUNTNUMBER 5 |
| CRYPTO | 4 | 4 | 4: PASSWORD 4 |
| CUSTOMERREF | 4 | 4 | 4: SSN 4 |
| BUILD | 6 | 1 | 1: IPV4 1 |
| PORT | 4 | 1 | 1: CREDITCARDCVV 1 |
| BIC, DATE, ERRORCODE, IPV6, MAC, NATIONALID, PARTIALCARD, PIN, SKU, TICKET, TOKEN | 4–6 each | 0 | 0 |

* **Long digit and alphanumeric identifiers** (tracking, serial, order, invoice, routing and meeting numbers) are taken for ACCOUNTNUMBER, IBAN or SSN. This is the same weakness as on `dev_v1` (36% False BLOCK) and on the held-out synthetic hard negatives.
* **Version strings** with four dotted numbers are taken for IPV4.
* **Out-of-scope credentials:**
  * API keys, crypto addresses and private keys are predicted as PASSWORD or ACCOUNTNUMBER;
  * in `strict`, 9 of the 12 ALLOW cases tagged `oos-secret` are blocked.
  * Under decision F (`docs/POLICY.md` §2) these count as false positives and false blocks. Blocking a secret is safe for confidentiality, but it is friction and it is outside the 13 categories.
* **Other harmless values are rarely mistaken.** Dates, error codes, PINs, SKUs, tickets, BIC codes, MAC and IPv6 addresses, national ids and partial cards caused no false positive.
* **The counts per type are small** (4–6 ALLOW cases each). Per-type rates are indicative only. A case can contain several types, and another finding may have caused the block.

**Leakage is low, but not zero.**
* `strict` allowed 2 of the 200 protected cases. Their tags are `difficult-positive`, `long` and `unfamiliar-format` (the tags overlap, and per-case details are not available to the developers).
* At entity level, 98.3% of gold entities are overlapped by some finding, so most of the 24 exact misses still block the document.
* **USERNAME** is the weakest label: recall 0.50 and precision 0.19. **SSN** values are often found with the wrong boundaries or type, and order or invoice numbers are taken for SSNs.

### 5.6 Independent result versus development results (`strict`)

| Set | Kind | Entity F1 | BLOCK F1 | False ALLOW | False BLOCK |
|---|---|---:|---:|---|---|
| `test` | synthetic, in-distribution | 0.984 | 0.998 | 3/3,055 (0.1%) | 11/1,068 (1.0%) |
| `challenge_v1_final` | hand-written by the developer, studied (regression only) | 0.830 | 0.954 | 2/95 (2.1%) | 7/57 (12.3%) |
| `dev_v1` | hand-written by the developer, used for selection | 0.685 | 0.806 | 0/56 (0.0%) | 27/75 (36.0%) |
| **`challenge_v2`** | **independent author, unseen, evaluated once** | **0.677** | **0.846** | **2/200 (1.0%)** | **70/200 (35.0%)** |

* **The independent result agrees with `dev_v1`:** entity F1 0.677 against 0.685, False BLOCK 35% against 36%. The selection set was therefore a fair proxy, and the development-time warning about false blocks is confirmed on independent text.
* **It is far below the synthetic in-distribution scores.** 0.98 on synthetic text measured the source distribution, not realistic prompts.
* `challenge_v1_final` looks better because its failures were studied during development; it is regression evidence only.

### 5.7 Limitations of this benchmark

* **Constructed, not sampled.** The cases are fictional text written for the benchmark.
  * Their composition is highly regular: 16 entities for most labels, every case tagged `enterprise`, and no case between 1,001 and 3,000 characters. That is a constructed test, not a sample of real employee prompts.
  * The 50/50 class balance is a design choice. In real traffic the share of protected prompts is unknown. BLOCK precision, and the practical cost of a 35% False BLOCK rate, depend on it.
* **One author, one evaluation, one training seed.** The confidence intervals cover sampling noise in these 400 cases only. They do not cover other authors, domains or seeds.
* **Small subgroups:**
  * look-alike types 4–6 cases each;
  * `oos-secret` 21 cases;
  * the two False ALLOWs are too few to characterise.
* **Aggregate-only error analysis.** The developers did not see the cases, by design, so causes are inferred from labels and tags, not from reading the text.
* **Not reported:** similarity of the cases to the training data (the optional `contamination` command is not among the shared artifacts); relaxed entity precision; entity-level confidence intervals.

## 6. `strict` versus `maximum`: the decision

* **`strict` is the primary mode, as declared before the evaluation, and the application uses it.** On `challenge_v2` it has the better precision and BLOCK F1, and 8 fewer false blocks.
* **`maximum` brings no measurable security benefit:**
  * the same entity recall (0.898);
  * one fewer False ALLOW, 1 against 2, with overlapping confidence intervals;
  * 8 more False BLOCKs and 60 more false-positive entities.

  `dev_v1` showed the same pattern (False BLOCK 32 against 27, no leakage difference).
* **`maximum` is retained** in `configs/inference/policy.json` and the code for reproducibility and future research, for example as a starting point for especially sensitive deployments. It is **not exposed as a user-facing option**, and the integration passes `"strict"` explicitly (`docs/INTEGRATION.md` §2.2).

## 7. Development history (summary)

| Step | What happened | Details |
|---|---|---|
| Original notebooks | The user's own exploration of `ai4privacy/pii-masking-200k` (English subset), an 80/10/10 split with template-leakage handling, BIO alignment, and mBERT fine-tuning. Reported validation F1 **0.9925** (token-level seqeval). | `archive/` (kept unchanged) |
| Investigation | The 0.9925 was a measurement artefact: out-of-scope entities were set to -100 and were invisible to the metric. On document-level character spans the same model scores **0.643** and blocks 74.5% of documents without a target. | `reports/history/INVESTIGATION.md`, `ROUND1_REPORT.md` |
| Round 1 | Label policy v2 (out-of-scope entities become `O`), format augmentation, deterministic rules. Hybrid E2 + rules: `challenge_v1` False ALLOW 2.2%, held-out formats 2.2%. | `reports/history/ROUND1_REPORT.md`, `COLAB_ROUND1_FIX.md` |
| Round 2 | Label policy v3 (CVV evidence), synthetic hard negatives (A) and difficult positives (B), runs R1–R4, and a selection rule fixed before any result. **R3 (B) selected.** R2 failed the leakage gate; R4 had the fewest false blocks but was ineligible under the rule. | `reports/history/ROUND2_PLAN.md`, `ROUND2_REPORT.md` |
| CPU studies | The checkpoint reproduces all 18,425 archived predictions. The window study kept 512/64/first. The IPv4 validation gate was rejected and removed. | `docs/METHODOLOGY.md` §7–8, `reports/evidence/` |
| Freeze | Repository consolidation; the system frozen on 2026-10-24 (commit `4907107`). | `configs/inference/frozen_system.json`, `reports/history/REPOSITORY_AUDIT.md` |
| Independent benchmark | Tooling hardened (`c8300ec`); `challenge_v2` sealed and evaluated once per mode on 2026-10-25. | §5, `reports/challenge_v2/` |

## 8. Data provenance and experiment lineage

See `docs/DATA_PIPELINE.md` §0. In short:
* The data is the English subset (43,501 records) of `ai4privacy/pii-masking-200k`, on the original 34,802 / 4,350 / 4,349 split, which was kept unchanged throughout.
* The labels were corrected by policy v3.
* R3 was trained on 49,685 documents: 34,802 original training documents, 12,196 format-A augmented copies and 2,687 synthetic difficult positives (`B_train`). Its epoch was selected on validation entity F1.

## 9. Model card: R3 `r2_e3b_positive` + rules v3

| | |
|---|---|
| **Intended use** | A local check, run before an employee's English prompt is sent to an external LLM, against *accidental* disclosure of the 13 categories. Research prototype. |
| **Not intended for** | Production enforcement without further validation (`docs/RISKS.md` §6); adversarial or obfuscated input; languages other than English; files and attachments; secrets outside the 13 categories (API keys, tokens), which are out of scope by policy. |
| **Model** | `google-bert/bert-base-multilingual-cased` (Apache-2.0), fine-tuned for 27 BIO labels: 2 epochs, lr 2e-5, effective batch 16, seed 42, fp16, on Colab. Plus deterministic rules v3 and a fail-closed policy. |
| **Training data** | The English subset of `ai4privacy/pii-masking-200k` (synthetic), relabelled by policy v3, with format augmentation and project-generated difficult positives (§8). |
| **Evaluation** | Synthetic in-distribution: entity F1 0.984. Hand-written development (`dev_v1`): 0.685. **Independent `challenge_v2`: entity F1 0.677; False ALLOW 1.0%; False BLOCK 35%** (§5). |
| **Known weaknesses** | Over-blocking of look-alike identifiers (tracking, serial, order, invoice numbers, versions) and of out-of-scope secrets; weak USERNAME detection; long documents; non-canonical IPv4 notations (`docs/RISKS.md` §3). |
| **Fairness and friction** | Names of public figures are blocked by policy. Names are detected from English-centred training data; behaviour on names from other cultures has not been measured. |
| **Provenance and licence** | The weights are a derivative of an Apache-2.0 model and of a dataset whose card states no licence (checked 2026-10-25). Redistribution beyond the project team is **unresolved**; the checkpoint is kept in private storage (`docs/INTEGRATION.md` §9). |

## 10. Limitations and future work

The full list is `docs/RISKS.md`. The most important points:

1. **False blocks.** One harmless prompt in three is blocked on the independent benchmark. The Round 2 hard-negative recipe (R4) cut `dev_v1` false blocks from 27 to 12 of 75, but it was not eligible under the pre-registered rule. A new round would have to re-establish leakage safety and then be tested on a **new** independent set: `challenge_v2` is now used.
2. **No real-world evidence.** A governed sample of real prompts, collected with consent and annotated by two people, and a shadow deployment that logs decisions without text, are the next evidence needed.
3. **Weak categories:** USERNAME, SSN boundaries, and identifiers taken for ACCOUNTNUMBER or IBAN.
4. **Long documents and window positions**, and non-canonical IPv4 notations (`docs/RISKS.md` §3).
5. **Stability:** one seed per configuration.
6. **Licensing** of the training data and therefore of the weights (§9).
