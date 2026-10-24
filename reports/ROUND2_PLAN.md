# Round 2: engineering plan and status

> **Status (2026-10-23): executed on Colab (T4) and analysed.** Results, verification and the selection outcome: `reports/ROUND2_REPORT.md`. This file is kept as the pre-run plan; the selection rule it refers to (`docs/METHODOLOGY.md` §6) was applied unchanged, and selected R3 (`r2_e3b_positive`) + rules v3.

Legend: **[done]** implemented and verified locally · **[prepared]** ready to run on Colab, not executed · **[decision]** needs the product owner.

## 1. Requirements as implemented

* **Scope.** Exactly the 13 labels, enforced in code (`labels.py`, `PolicyConfig`, all validators). There is no API-key or token layer, and out-of-scope credentials are never relabelled as PASSWORD.
* **Person names.** Detected regardless of public-figure status, with no whitelist (`docs/POLICY.md` §3).
* **CVV.** In scope, but only with contextual evidence (annotation policy v3).
* **Priorities.** Security first (False ALLOW), usability second (False BLOCK). Both are always reported together, and the trade-off is left to the product owner with evidence, not an invented budget.

## 2. Gaps found against the final policy, and what was done

| # | Gap (evidence) | Fix | Status |
|---|---|---|---|
| 1 | `challenge_v1` scored public figures as negatives (cases neg-011/027/040), contradicting the final policy | policy overlay `data/challenge/challenge_v1_overlay_final_policy.json` → derived set `challenge_v1_policy`; the frozen file is untouched and both are reported | [done] |
| 2 | 15.8% of synthetic training CVVs have no supporting context ("sharing your 482 or 1234 can lead to fraud"). This teaches "a 3-digit number = CVV" and matches the `1234`/UUID-fragment → CVV false blocks | annotation policy v3: such CVVs are ignored (`labels.cvv_has_evidence`; strong cue, card context, or weak cue + card word) | [done] |
| 3 | `chat-033` (missed CVV) | investigated: "the 3 digits on the back are 204 … security code box" carries sufficient evidence, so it is a **genuine failure**, not an ambiguous annotation; the rules now read cues after the value too | [done] |
| 4 | Rules mapped numeric door `passcode`s to PASSWORD (3 validation FPs on PINs) | numeric passcodes are PINs (out of scope); alphanumeric ones stay PASSWORD | [done] |
| 5 | No security-policy layer, modes, fail-closed handling, or inference entry point | `policy.py`, `pipeline.py`, `__main__.py`, `configs/inference/policy.json`, 7 pipeline tests | [done] |
| 6 | No independent development data: synthetic validation is saturated and `challenge_v1` has been studied | `data/dev/dev_v1.txt` (135 cases, frozen `3ea038b1…`), written **before** the generators | [done] |
| 7 | Documents were stale (Arabic/regex scope) | `README.md` rewritten; `docs/` (policy, annotation, data, methodology, architecture, case format, challenge_v2 spec, risks) | [done] |
| 8 | No interface for an independent hidden benchmark | `scripts/challenge_v2.py` (validate/seal/contamination/evaluate, ledger, text-free outputs), 5 tests, bundle-builder refusal, git-ignore | [done] |
| 9 | **Found during this work:** stored round-1 predictions were silently scored against changed v3 texts (`test_long`: 43 docs differ, `test_format_shift`: 13), because evaluation matched documents by id only | `runio.check_provenance` in `evaluate.py` and all analysis scripts (refuses mismatched eval sha256); `scripts/retarget_predictions.py` reuses predictions only where texts are byte-identical; regression test | [done] |

## 3. Rules v3 (decided on validation and dev only)

| Change | Evidence |
|---|---|
| CVV: shared cue vocabulary, JSON keys (`security_code`), cue after the value, "security code" needs card context | dev CVV recall 0.6 → 1.0; a validation FP ("0004 is your security code for the consultation") removed |
| PASSWORD/USERNAME in JSON/YAML (`"password": "…"`), `IDENTIFIED BY`, `CREATE USER`, `psql -U`, `.netrc`, `logged in as`, `/home/<user>/` | dev USERNAME recall 0.24 → 0.71, PASSWORD 0.38 → 0.62 |
| IPv4: an explicit IP cue overrides version context; context-free small-first-octet quads (versions) need network context | validation false negative fixed; hybrid validation unchanged (IPv4 P/R 1.0/1.0) |
| Phone and card suppressed after identifier cues (tracking, order, SKU, bridge, …); cards need a card grouping and must not be part of a longer number; 13-digit cards need a card cue | rule false blocks on the hard-negative **training** families 138 → 76 |

Net effect:
* **dev_v1, rules only:** precision 0.805 → 0.920, recall 0.384 → 0.535, FAR 44.6% → 32.1%, FBR 4.0% → 1.3%.
* **validation:** hybrid unchanged or better.
* **Caveat:** dev and rules share an author, so the dev gain is optimistic. That is why validation non-regression was also required.

## 3b. Current baseline under the final policy (no retraining; regression only)

The round-1 E2 predictions were reused where the v3 texts are byte-identical (`scripts/retarget_predictions.py`; refused for `test_unseen_value`, `test_format_shift`, `test_long`, which R0 re-predicts).

| E2 + … | Set | False ALLOW | False BLOCK | Entity F1 | BLOCK docs fully caught |
|---|---|---|---|---|---|
| rules_v2 | `challenge_v1_policy` (95 BLOCK / 56 ALLOW) | 3 (3.2%) | 9 (16.1%) | 0.795 | 86.3% |
| rules_v3 | `challenge_v1_policy` | 2 (2.1%) | 8 (14.3%) | 0.806 | 89.5% |
| rules_v3 | `validation` | 3 / 3,017 | 13 / 1,154 | 0.986 | — |
| rules_v3 | `test` | 0.1% | 1.2% | 0.983 | — |

**Not independent evidence.** `challenge_v1` failures were studied, and one rules-v3 change (reading CVV cues after the value) generalises a studied failure (`chat-033`). The rules were frozen on validation and dev before these numbers were computed.

## 4. Round-2 data (experiments A and B)

Built by `scripts/build_synth_round2.py`; see `data/synth/round2/manifest.json`. Overall:
* 48 template families (value group × document frame), 142 templates.
* One whole family per value group held out (11 families), never trained on.
* Quality gates: annotation policy, CVV evidence, no unannotated names, deduplication, and the contamination guard.

| Bucket | Docs | Families / templates | Role |
|---|---|---|---|
| A_train | 3,173 | 20 / 61 | hard negatives (+ 3 mixed families with one clear target) |
| B_train | 2,687 | 17 / 46 | difficult positives (lowercase names, structured PII, credentials in JSON/YAML/SQL/env/CLI, CVV with context, bank details) |
| synth_A_heldout | 960 | 6 / 23 | evaluation: unseen hard-negative families (ALLOW only) |
| synth_B_heldout | 776 | 5 / 12 | evaluation: unseen difficult-positive families |

**Contamination.** The first template draft paraphrased `dev_v1` cases almost verbatim, because the same engineer wrote both. It was rewritten before generation. Final maximum TF-IDF similarity to any dev or challenge case is 0.20, with 0 documents dropped by the 0.5 guard and 33 dropped for reusing a dev/challenge value.

## 5. Experiments [prepared]: `notebooks/colab/06_round2_experiments.ipynb`, bundle `round2-r1`

| Stage | Run | One factor vs parent | Parent |
|---|---|---|---|
| R0 | `e2_mbert_v2_fmtA` | none: the round-1 checkpoint scored on the v3 suite | — |
| R1 | `r2_e2_v3` | label policy v2 → v3 | E2 |
| R2 | `r2_e3a_hardneg` | + A_train | R1 |
| R3 | `r2_e3b_positive` | + B_train | R1 |
| R4 | `r2_e4_combined` | + A_train + B_train | R1 |

* **Selection.** The rule is fixed in advance (`docs/METHODOLOGY.md` §6) and applied mechanically by `scripts/analyze_round2.py`. Every candidate is scored as model + rules_v3 on `dev_v1`, the held-out families, format shift and test.
* **Operating points.** `scripts/operating_points.py` on `dev_v1` produces the False ALLOW / False BLOCK table; the product owner picks the modes [decision].
* **Calibration** of the selected model: `scripts/calibration.py`.

**Verification so far (local CPU, no GPU):**
* 111 tests pass; 109 pass and 2 skip from the extracted bundle (final bundle sha256 `505e76c5…`).
* The full notebook path ran end to end in smoke mode on the final bundle: setup, R0–R4, resume, complete archive. Only the GPU path, real-size training and Drive I/O are unverified.

## 6. Decisions requested from the product owner (resolved 2026-10-23)

1. **Fail-closed behaviour.** Confirmed (decision D): BLOCK on inspection errors and on inputs over 100,000 characters, with an explanation that names the real reason.
2. **Operating point.** Evidence is in `reports/ROUND2_REPORT.md` §8. `strict` is recommended as the default; `maximum` stays optional.
3. **Public-figure friction.** Policy unchanged (decision B).
4. **Out-of-scope secrets.** Decided (decision F): an API key predicted as PASSWORD is an entity false positive, and a False BLOCK on a document without targets. Neutrality is withdrawn; see `challenge_v1_final`.
