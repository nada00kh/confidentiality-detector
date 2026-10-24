# Round 1 results: engineering report

**Run provenance.**
* Colab Tesla T4, Python 3.13.15, torch 2.11.0+cu130, transformers 5.20.1.
* Bundle `round1-r2`: every file is byte-identical to the repository (`BUNDLE_INFO.json` checked).
* Archive `round1_results.zip` is complete (A, B, C ok), and all 57 members match `RESULTS_MANIFEST.json` hashes.
* Re-scoring the raw predictions locally reproduces Colab's metrics exactly for all three models.
* Raw outputs are in `results/round1/`. Derived metrics are in `reports/runs/*/metrics.json` and `reports/round1_analysis.json` (`python scripts/analyze_round1.py`).

**Terms.**
* FAR = False ALLOW Rate = sensitive documents let through ÷ sensitive documents (the leak rate).
* FBR = False BLOCK Rate = harmless documents blocked ÷ harmless documents.
* "Caught" = share of gold entities overlapped by *any* prediction, which is what matters for leakage.

Every number below was measured. Hypotheses and recommendations are labelled as such.

---

## 1. Executive summary

1. **The 0.9925 F1 is reproduced exactly, and it is an artefact of the label/metric design.** Re-scored with out-of-scope entities visible, the same checkpoint has validation precision **0.476** and F1 **0.643**. In document terms it blocks **74.5%** of documents that contain no target entity.
2. **Fixing the labels alone (E1) fixes synthetic performance but *increases* realistic leakage.** On the hand-written challenge set FAR rose from 9.8% to **19.6%** (paired exact McNemar p = 0.004). The original model's apparent robustness came from flagging everything.
3. **Format augmentation (E2) is the change that generalises.** Held-out-format FAR fell from 10.5% to **2.8%** and challenge FAR from 19.6% to **7.6%** (p = 0.003), with no cost on synthetic test.
4. **The best system is the hybrid E2 + rules_v2**, designed before any model results existed.
   * Challenge: **FAR 2.2%** (2/92, 95% CI 0–5.4%) and FBR 18.3% (11/60).
   * Held-out formats: FAR 2.2%.
   * It dominates the original model on both error types (fewer leaks, p = 0.04; fewer false blocks, p < 0.001) and beats Presidio on leakage (1 vs 19 discordant docs, p < 0.001).
5. **Main remaining weakness: false BLOCKs on realistic look-alikes.** These are order, tracking and meeting IDs, versions, math, and public figures (25% of hard-negative prompts). Almost all come from the model at high confidence, because the synthetic training data contains no such negatives. Recall gaps remain on lowercase or context-free names, lowercase usernames, and cue-less CVVs.

No further training is needed to *understand* round 1. The next useful experiment is data-centric: hard negatives and casing (§8). A different backbone isn't justified by the evidence yet.

---

## 2. How much of 0.9925 was methodology? (Stage A, validation split, same checkpoint)

| Row | Scoring | P | R | F1 |
|---|---|---:|---:|---:|
| A | original notebook: token-level seqeval, `-100 → O` in gold **and** prediction | 0.9908 | 0.9942 | **0.9925** |
| B | same, but `-100` positions dropped | 0.9908 | 0.9942 | 0.9925 |
| C | document-level character spans, original gold (out-of-scope entities still invisible) | 0.9853 | 0.9899 | 0.9876 |
| D | document-level character spans, **corrected gold** (out-of-scope entities scoreable, IP→IPV4) | **0.4764** | 0.9901 | **0.6433** |

Attribution:
* **A = B.** The `-100 → O` conversion is not itself what inflates the score. Because whole out-of-scope entities are `-100`, dropping them or setting them to `O` produces the same entity sets.
* **A → C (−0.005).** Moving from overlapping token windows to document-level character spans changes almost nothing. Windowing and alignment were not the problem.
* **C → D (−0.344 F1, −0.51 precision).** All of the inflation comes from what the ignored positions *were*: 9,172 out-of-scope entity spans that the model was neither trained against nor penalised for.
  * Under D, the model makes **5,117 hard-negative false positives**, versus 69 other FPs.
  * Top patterns: IPV6→PASSWORD 560, BITCOINADDRESS→PASSWORD 303, COMPANYNAME→LASTNAME 298, IP(v6)→PASSWORD 238, CITY→STREET 218, PHONEIMEI→PHONENUMBER 208, DATE→PHONENUMBER 194.
  * Recall is genuinely high (0.990). The problem was precision that could not be seen.

**Conclusion:** about 0.35 of the 0.99 F1 was methodology. The original checkpoint's real behaviour on synthetic data is "flag almost any PII-like span": validation FBR **74.5%**, test FBR 72.8%, long-document FBR 100%.

## 3. Model comparison (argmax decoding)

| System | Set | Entity P | Entity R | Entity F1 | Caught | FAR | FBR |
|---|---|---:|---:|---:|---:|---:|---:|
| original (ckpt-4352) | test | 0.475 | 0.989 | 0.641 | 1.000 | 0.000 | **0.728** |
| E1 v2 labels | test | 0.983 | 0.986 | 0.984 | 0.997 | 0.001 | 0.010 |
| E2 v2 + fmt-A | test | 0.981 | 0.986 | 0.984 | 0.998 | 0.001 | 0.011 |
| **E2 + rules_v2** | test | 0.979 | 0.986 | 0.983 | 0.998 | 0.001 | 0.013 |
| rules_v2 | test | 0.985 | 0.322 | 0.485 | 0.323 | 0.544 | 0.002 |
| Presidio (min 0.3) | test | 0.632 | 0.539 | 0.582 | 0.656 | 0.216 | 0.153 |
| original | test_format_shift | 0.359 | 0.557 | 0.436 | 0.845 | 0.042 | — |
| E1 | test_format_shift | 0.591 | 0.542 | 0.566 | 0.819 | **0.105** | — |
| E2 | test_format_shift | 0.587 | 0.621 | 0.603 | 0.947 | 0.028 | — |
| **E2 + rules_v2** | test_format_shift | 0.758 | 0.750 | **0.754** | **0.961** | **0.022** | — |
| rules_v2 | test_format_shift | 0.965 | 0.379 | 0.544 | 0.390 | 0.471 | — |
| Presidio | test_format_shift | 0.691 | 0.545 | 0.610 | 0.658 | 0.218 | — |
| original | test_long | 0.041 | 0.971 | 0.079 | 1.000 | 0.000 | 1.000 |
| E2 | test_long | 0.761 | 0.971 | 0.854 | 1.000 | 0.000 | 0.143 |
| **E2 + rules_v2** | test_long | 0.744 | 0.971 | 0.843 | 1.000 | 0.000 | 0.143 |
| original | **challenge_v1** | 0.471 | 0.627 | 0.538 | 0.819 | 0.098 | 0.483 |
| E1 | challenge_v1 | 0.692 | 0.617 | 0.652 | 0.746 | 0.196 | 0.200 |
| E2 | challenge_v1 | 0.735 | 0.720 | 0.728 | 0.850 | 0.076 | 0.167 |
| **E2 + rules_v2** | challenge_v1 | 0.797 | 0.813 | **0.805** | **0.907** | **0.022** | 0.183 |
| rules_v2 | challenge_v1 | 0.978 | 0.472 | 0.636 | 0.477 | 0.283 | 0.017 |
| Presidio | challenge_v1 | 0.803 | 0.653 | 0.720 | 0.710 | 0.217 | 0.117 |

Challenge document rates with bootstrap 95% CIs (92 BLOCK / 60 ALLOW docs):

| System | FAR | FAR CI | FBR | FBR CI |
|---|---:|---|---:|---|
| original | 0.098 | 0.043–0.163 | 0.483 | 0.350–0.617 |
| E1 | 0.196 | 0.120–0.283 | 0.200 | 0.100–0.317 |
| E2 | 0.076 | 0.033–0.130 | 0.167 | 0.083–0.267 |
| **E2 + rules_v2** | **0.022** | **0.000–0.054** | 0.183 | 0.083–0.283 |
| rules_v2 | 0.283 | 0.185–0.380 | 0.017 | 0.000–0.050 |
| Presidio | 0.217 | 0.141–0.304 | 0.117 | 0.050–0.200 |

Paired exact McNemar tests on per-document correctness. Discordant counts are given as (first system correct only, second system correct only).

| Comparison | Set | BLOCK docs (leaks) | ALLOW docs (false blocks) |
|---|---|---|---|
| original vs E1 | challenge | (9, 0), **p = 0.004**: E1 leaks more | (0, 17), p < 0.001: E1 blocks less |
| E1 vs E2 | challenge | (1, 12), **p = 0.003** | (1, 3), p = 0.63 |
| E1 vs E2 | format shift | (13, 248), p < 0.001 | — |
| E2 vs E2 + rules | challenge | (0, 5), p = 0.063 (n.s.) | (1, 0), p = 1.0 |
| E2 vs E2 + rules | format shift | (0, 17), p < 0.001 | — |
| original vs E2 + rules | challenge | (1, 8), **p = 0.039** | (0, 18), p < 0.001 |
| Presidio vs E2 + rules | challenge | (1, 19), p < 0.001 | (8, 4), p = 0.39 |

In-distribution, the synthetic test cannot separate E1, E2 and E2 + rules: all are at about 0.98 F1 and differences are within noise. Only the held-out sets discriminate.

## 4. Per-class analysis

Strict F1, with caught-any-type in parentheses.

| Label | E2 test | E2 format-shift | E2+rules format-shift | E2 challenge | E2+rules challenge (support) |
|---|---|---|---|---|---|
| PASSWORD | 1.00 (1.00) | 0.65 (0.96) | — | 0.43 (0.71) | (14) |
| USERNAME | 0.99 (1.00) | 0.39 (0.94) | — | 0.50 (0.60) | (20) |
| EMAIL | 1.00 (1.00) | 0.64 (0.99) | 1.00 via rules | 0.87 (0.93) | 1.00 via rules (15) |
| PHONENUMBER | 1.00 (1.00) | 0.47 (1.00) | — | 0.73 (1.00) | (12) |
| FIRSTNAME | 0.97 (1.00) | 0.70 (0.97) | — | 0.78 (0.85) | (46) |
| LASTNAME | 0.97 (0.99) | 0.80 (0.99) | — | 0.85 (0.88) | (34) |
| SSN | 1.00 (1.00) | 0.78 (1.00) | — | 0.86 (1.00) | (6) |
| CREDITCARDNUMBER | 0.99 (1.00) | **0.20 (1.00)** | rules 0.97 | 0.50 (1.00) | (6) |
| CREDITCARDCVV | 0.93 (1.00) | 0.16 (0.38) | — | 0.33 (0.50) | (4) |
| IBAN | 0.99 (1.00) | **0.00 (1.00)** | rules 1.00 | 0.60 (1.00) | (6) |
| ACCOUNTNUMBER | 1.00 (1.00) | 0.24 (0.79) | — | 0.71 (0.86) | (7) |
| STREET | 0.96 (1.00) | 0.69 (0.78) | — | 0.93 (1.00) | (7) |
| IPV4 | 1.00 (1.00) | 1.00 (1.00) | — | 0.84 (0.88) | (16) |

Full per-class tables for every model and set are in `reports/runs/<run>/metrics.json`.

Observations:
* **Structured values in unseen formats: the model notices them but fragments them.** For grouped IBANs and card numbers, caught is 1.00 while strict F1 is 0.00–0.20: "DE89 3704 …" is split into several spans or partly mistyped. For blocking this is harmless. For redaction or reporting it is wrong. The validators fix it: IBAN, card and email reach F1 1.00 under the hybrid.
* **CVV and account numbers in new formats are weak:** CVV caught 0.38 with 4-digit values, account caught 0.79 with dashed values. These are short digit strings whose identity depends on context. Family-A augmentation used 3-digit CVVs and undashed accounts, so family B tests genuine extrapolation.
* **Passwords and usernames:** E1 → E2 raises format-shift caught from 0.62 → 0.96 and 0.55 → 0.94. On the challenge set they're still the weakest context classes (caught 0.71 and 0.60 for E2 alone).
* **Names are robust in-distribution** (0.97) but drop on lowercase and unfamiliar names: format-shift FIRSTNAME F1 0.70 (30% of names were lowercased in family B), and challenge misses `priya`, `becky`, `jonas`, `sam okoro`.
* **Per-class FAR/FBR.** FAR and FBR are document-level quantities. Per class, the equivalent leak measure is 1 − caught, reported above. The challenge per-tag breakdown below gives the document-level view.

Challenge set by category, false ALLOW / false BLOCK:

| Tag (BLOCK/ALLOW docs) | original | E1 | E2 | **E2+rules** | Presidio | rules |
|---|---|---|---|---|---|---|
| chat (40/0) | 7/0 | 9/0 | 4/0 | **1/0** | 11/0 | 16/0 |
| email (29/0) | 2/0 | 4/0 | 1/0 | **0/0** | 3/0 | 7/0 |
| code (21/0) | 0/0 | 6/0 | 2/0 | **0/0** | 6/0 | 2/0 |
| form (12/0) | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 2/0 |
| no explicit cue (17/0) | 3/0 | 3/0 | 1/0 | 1/0 | 7/0 | 10/0 |
| lowercase (4/0) | 3/0 | 4/0 | 1/0 | 1/0 | 1/0 | 4/0 |
| long (3/1) | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| hard negatives (0/44) | 0/28 | 0/12 | 0/10 | 0/11 | 0/7 | 0/1 |
| public names (0/4) | 0/4 | 0/4 | 0/2 | 0/2 | 0/4 | 0/0 |
| clean prompts (0/16) | 0/1 | 0/0 | 0/0 | **0/0** | 0/0 | 0/0 |

All false BLOCKs of the trained models fall on hard negatives. None falls on the 16 ordinary prompts.

## 5. Rules vs Presidio vs transformer vs hybrid

| | Strengths (measured) | Weaknesses (measured) |
|---|---|---|
| **rules_v2** | Precision 0.98–0.99 everywhere. Exact and format-independent for IBAN/card/email/IPv4 (F1 1.00 on format shift). 0.1 ms/doc. | Cannot see names or streets. Leaks 28% of challenge docs and 54% of synthetic test docs. |
| **Presidio** | Strong on email/IBAN/card/IPv4. FBR 12% on challenge. | No PASSWORD, USERNAME, CVV or STREET. PERSON fires on out-of-scope names (long-doc FBR 96%). Leaks 22% on challenge. |
| **Transformer (E2)** | Context-dependent entities (names, passwords, usernames, streets). Best single detector on leakage (challenge FAR 7.6%). | Fragments unseen structured formats. Confident false positives on numeric look-alikes. |
| **E2 + rules_v2** | Combines both: lowest leakage on every held-out set; best strict F1 on format shift (0.754) and challenge (0.805). | Inherits the model's false BLOCKs, plus one rule FP (a version number that is a syntactically valid IPv4). |

**Architecture decision.** I recommend **E2 + rules_v2 (argmax)** as the current system, for three reasons:
* It is the only configuration whose leak rate is low on *both* independent held-out sets (2.2% / 2.2%).
* The hybrid rule was pre-specified (`DEFAULT_RULE_PRIORITY`) rather than fitted.
* Its added cost is negligible (0.1 ms).

On mBERT vs a different backbone: no other backbone was trained, so there is **no evidence for or against** a switch. The failures in §6 are data-coverage failures, such as negatives and casing absent from training, not capacity failures (in-distribution F1 0.98). A backbone change alone would not be expected to fix them.

## 6. Failure analysis (E2 + rules_v2 on the challenge set; values shown as shapes only)

**False ALLOWs (2 of 92):**
* `chat-033`: CVV `999` written as "the 3 digits on the back are …", with no cue word.
* `form-009`: lowercase, context-free name list ("attendees: aaa aaaaa, aa aa, aaaaa aaaaa").

**Missed entities inside documents that were still blocked thanks to other entities (10 docs).** Each would be a leak if it were the only sensitive item:
* lowercase given names (`chat-002`, `chat-031`, `mail-007`);
* names inside SQL `VALUES (...)` (`code-008`);
* lowercase usernames without "username:" (`chat-018`, `chat-030`, `code-017`, `long-002`);
* passwords after "with" or in a JSON field (`chat-008`, `code-020`).

**False BLOCKs (11 of 60):**

| Doc | Gold | Predicted | Source |
|---|---|---|---|
| neg-002 | order id | CREDITCARDNUMBER | model, 0.98 |
| neg-004 | UUID fragment | CREDITCARDCVV | model, 1.00 |
| neg-007 | arithmetic | PHONENUMBER | model, 0.95 |
| neg-015 | UPS tracking | IBAN | model, 1.00 |
| neg-020 | error code | ACCOUNTNUMBER | model, 1.00 |
| neg-027 | public figures | FIRSTNAME | model, 0.77–0.86 |
| neg-037 | PIN policy text | CREDITCARDCVV | model, 0.93 |
| neg-040 | public figure | FIRSTNAME | model, 0.93 |
| neg-044 | meeting id | SSN | model, 1.00 |
| neg-045 | k8s version | IPV4 | model, 0.63 |
| neg-001 | version `1.2.3.4` | IPV4 | rule (a syntactically valid IPv4; genuinely ambiguous) |

* **[F] 10 of 11 come from the model, 8 of them at ≥ 0.93 confidence**, so thresholding cannot remove them.
* **[H] Cause:** the synthetic ALLOW documents contain only ai4privacy's out-of-scope entity types, never order, tracking or meeting IDs, arithmetic, error codes or public figures. The model has never seen these as negatives.

**Synthetic hard negatives that remain after the fix (E2, test):** FBR 1.1%, 12 of 1,068 documents. The long-document FBR of 14.3% matches that per-document rate compounding over the median 15 concatenated documents (1 − 0.989¹⁵ ≈ 15%). It is not a windowing failure: long-document recall 0.971, FAR 0.

## 7. Operating point

The rule was fixed beforehand: on validation, take the lowest token threshold within a +1 pp FBR and −0.01 F1 budget. It selected **t = 0.05, the bottom of the grid**, because validation is saturated (F1 0.983–0.985 across all thresholds). Effect on held-out sets for E2 + rules:

| Set | argmax FAR / FBR | t = 0.05 FAR / FBR |
|---|---|---|
| test | 0.001 / 0.013 | 0.000 / 0.022 |
| format shift | 0.022 / — | 0.011 / — |
| long | 0.000 / 0.143 | 0.000 / 0.250 |
| challenge | 0.022 / 0.183 | **0.000** / **0.250** |

This is a genuine leak-vs-friction trade-off, and synthetic validation cannot arbitrate it. **Recommendation:**
* Ship argmax as the default.
* Expose the threshold as a policy setting: t = 0.05 for "high-security" mode.
* Re-select it on a realistic development set (§8).

## 8. Remaining risks and recommended next steps

**What this evaluation does not establish:**
* **Challenge-set size and authorship.** There are 92 BLOCK and 60 ALLOW cases (CIs ±5–10 pp). The cases and the rules were written by the same engineer, so shared assumptions about "realistic" text may favour the hybrid. I have now inspected `challenge_v1` failures, so **it can no longer serve as an unbiased test for any change made from here on.**
* **Real traffic is unrepresented.** No real (redacted) user prompts were evaluated, and the base rate of BLOCK vs ALLOW in production is unknown. FBR on ordinary prompts (0/16) is based on very few cases.
* **Single seed per experiment.** In-distribution differences between E1 and E2 are within noise. The out-of-distribution differences are significant.
* **Ignored annotations.** MIDDLENAME and MASKEDNUMBER are ignored, so behaviour on them is unmeasured.
* **Scope gap.** API keys and tokens are out of scope, though clearly sensitive.
* **Latency was timed on this laptop's CPU with the mBERT architecture**, not on target hardware. Prompts take 37 ms median (p95 219 ms); 600–1,000-token documents take 0.6–2.9 s.

**Recommended round 2 (not executed; for your approval).** One variable per run, reusing the E2 recipe:
1. **Decisions needed from you:**
   * Should public figures' names be BLOCK or ALLOW?
   * Should API keys and tokens enter the scope?
   * What false-BLOCK budget is acceptable to users?
2. **New evaluation data before any training:**
   * a realistic **dev set** (for operating points, about 300 cases);
   * **challenge_v2**, written by someone other than the rules author, ideally including real redacted prompts, frozen before scoring.
3. **E3a, hard-negative augmentation.** Template-diverse ALLOW documents containing order, tracking, meeting and ticket IDs, versions, arithmetic, UUIDs, hashes, error codes and prices. Hold out whole template families for evaluation.
   * Expected effect (hypothesis): lower FBR on hard negatives, with FAR checked for regressions.
4. **E3b, casing and context augmentation.** Lowercase names and usernames, names in SQL/CSV/JSON, passwords in JSON or after "with".
5. **Only then a backbone comparison** (e.g. an English DeBERTa-v3-base, and a distilled model for latency) under the same protocol, if E3 plateaus.
6. **Rules:** keep them validation-driven. A cue-less CVV is left to the model; adding a rule for it would overfit to `chat-033`.

**Status of artifacts:**
* The original checkpoint is unchanged; its weight hash was recorded before and after stage A.
* E1 and E2 best checkpoints are on Drive (`round1_rerun/checkpoints/`).
* For local deployment or further analysis, download `round1_rerun/checkpoints/e2_mbert_v2_fmtA/` (about 709 MB).

---

## Addendum (2026-10-23): final product decisions after this report

The numbers above are unchanged and remain the round-1 record. Three later decisions change how some of them should be read:

* **Public figures are protected names.** Under the final policy, two of the eleven E2 + rules false BLOCKs (`neg-027`, `neg-040`) are correct BLOCKs, and `neg-011` (allowed) becomes a missed name. Policy-consistent re-scoring uses the overlay set `challenge_v1_policy` (`reports/ROUND2_PLAN.md`).
* **API keys and tokens stay out of scope.** The recommendation in §8 to consider adding them is withdrawn. Out-of-scope credentials are evaluated as ambiguous.
* **CVV needs contextual evidence** (annotation policy v3). `chat-033` was re-examined: it carries sufficient evidence and remains a genuine miss.

`challenge_v1` has been studied in detail and is no longer used as independent evidence. That role passes to the independently written `challenge_v2` (`docs/CHALLENGE_V2_SPEC.md`).
