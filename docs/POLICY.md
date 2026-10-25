# Product and detection policy

Policy version 1.0. This document is normative: data generation, annotation, training, evaluation and inference all implement it. Where code and this document disagree, that is a bug.

## 1. Purpose and workflow

Confidentiality Detector stops employees from *accidentally* sending protected information to an external LLM. It runs locally, inside the organisation's boundary, before the prompt leaves:

```
employee prompt ─► local inspection ─► findings (13 categories) ─► security policy ─► BLOCK  (prompt is not sent)
                                                                                  └► ALLOW  (prompt may be sent)
```

It has two duties, in priority order:
1. **Prevent leakage**: minimise the False ALLOW rate, i.e. protected information that gets through.
2. **Avoid needless friction**: keep the False BLOCK rate as low as the first duty allows.

It is not a general secret scanner, a DLP system for files, or a defence against a user who deliberately obfuscates data (see `docs/RISKS.md`).

## 2. Scope: exactly 13 categories

`PASSWORD, USERNAME, EMAIL, PHONENUMBER, FIRSTNAME, LASTNAME, SSN, CREDITCARDNUMBER, CREDITCARDCVV, IBAN, ACCOUNTNUMBER, STREET, IPV4`

The set is defined once, in `src/confidentiality_detector/labels.py` (`TARGET_LABELS`). It is enforced:
* by `PolicyConfig`, which rejects any blocking label outside the set;
* by the BIO label mapping, which is validated on every model load;
* by every data validator (`synth.validate_synthetic`, `train.load_extra_train`, `challenge.parse_case`).

Per-label annotation rules are in `docs/ANNOTATION_GUIDELINES.md`.

**Explicitly out of scope** (decision 2026-10-23):
* API keys, access and authentication tokens, private keys;
* one-time codes, meeting passcodes, door/locker PINs;
* IPv6, MAC addresses, IMEIs, crypto addresses, BIC/SWIFT codes, routing and sort codes;
* order, ticket, invoice, tracking and similar identifiers.

There is no separate secret-detection layer, and no new labels or categories will be added without explicit authorisation.

Out-of-scope credentials are never relabelled as PASSWORD to widen coverage.

**Decision F (2026-10-23, after Round 2): an API key or access token is not a PASSWORD.**
* If the detector labels an out-of-scope key or token as PASSWORD, that is an **entity-level false positive** wherever the gold annotation marks the value as out of scope (`[[!APIKEY:…]]`, `[[!TOKEN:…]]`).
* If the document contains no target entity, blocking it is a **False BLOCK**.
* Such values are therefore annotated as out-of-scope look-alikes, never as ignored (`~`) spans. `scripts/challenge_v2.py validate` rejects `~SECRET`, `~APIKEY`, `~TOKEN` and similar.
* This does **not** widen the scope. Keys are neither trained as targets nor added as a category.
* Effect on `challenge_v1` (case `code-013`, an AWS secret key): the derived set `challenge_v1_final` applies the decision through a second overlay version. R0, R1 and R2 flag the key and gain one False BLOCK; R3 and R4 do not flag it in `strict` mode. `dev_v1` contains no API-key case.

## 3. Person names (final policy)

* A clearly identifiable person's given name is FIRSTNAME and family name is LASTNAME, **whether or not the person is publicly known**. A public figure can be party to a confidential negotiation, contract or customer relationship.
* There is **no celebrity whitelist**. Public-person names are never used as training negatives and are never scored as false positives.
* Company names, product names, place names and ordinary words are **not** person names, even when they look like one: Ford, Dell, Jenkins, Paris, Jordan (the country), "I hope we will finish by May".
* Fictional characters are name-shaped but not persons. The policy does not decide them, so they are annotated as ambiguous.
* A single-word name with no FIRST/LAST distinction (a mononym) blocks the document, but is ignored for entity-type scoring.

**Implication.** Harmless public-information prompts that name a real person are blocked, for example "Summarise Marie Curie's discoveries" or "Prepare notes for our call with ⟨CEO name⟩".
* Under this policy those are **correct BLOCKs**, not false blocks, so they do not appear in the False BLOCK rate.
* They are nonetheless a usability cost the product owner accepts.
* Re-scoring `challenge_v1` under this policy (`challenge_v1_policy` overlay) turns 3 public-figure prompts into BLOCK cases and 1 (fictional characters) into an ambiguous case.
* Changing this behaviour, for example with a context-sensitive exemption, is a product decision and has not been implemented.

## 4. Ambiguous values

A value is a target only when the text provides evidence for its category. The format alone is not enough when the format is shared by harmless data.

* **CREDITCARDCVV** (policy v3, `labels.cvv_has_evidence`). A 3–4 digit number is a CVV only if one of these holds:
  * a strong cue appears within 60 characters before or 40 after: CVV/CVC/CCV/CSC/CVN, "card verification …", "digits on the back", "back of the card";
  * card context appears within 120 characters: a card number or an expiry date;
  * the weak cue "security code" appears **together with** a card word (card, visa, credit, …).

  "Security code" alone also names one-time codes and PINs, so it is not enough. An isolated "482" is never a CVV. Source labels without evidence (15.8% of the synthetic training CVVs, e.g. "sharing your 482 or 1234 can lead to fraud") are *ignored*: neither trained nor scored.
* **Short numbers in ordinary context** (room 482, 12 boxes, page 204, port 5432) are not targets. They appear as hard negatives in the Round 2 training data.
* **Network ranges, loopback and masks** (10.0.0.0/8, 127.0.0.1, 255.255.255.0) are ambiguous. A host IPv4 address, including a private one, is IPV4.
* **Version numbers that are syntactically IPv4** (firmware 2.4.1.7) are not IPV4 when the context says "version / build / firmware …". Without context they are genuinely ambiguous, and the rule detector may block them.
* A document whose only annotations are ambiguous is **AMBIGUOUS** and is excluded from document metrics. A case file may also mark a document AMBIGUOUS explicitly.

## 5. BLOCK/ALLOW logic

Implemented in `src/confidentiality_detector/policy.py`:

| Situation | Decision | Reason code |
|---|---|---|
| ≥ 1 finding in a blocking category (all 13) | **BLOCK** | `SENSITIVE_ENTITIES` |
| no finding | ALLOW | `NO_SENSITIVE_ENTITIES` |
| empty / whitespace input | ALLOW | `EMPTY_INPUT` |
| input longer than `max_chars` (default 100,000) | **BLOCK** (`on_oversize`) | `INPUT_TOO_LARGE` |
| any exception during inspection (model failure, out of memory, …) | **BLOCK** (`on_error`) | `INSPECTION_ERROR` |
| input that is not a string | `TypeError` (caller bug) | — |

**Fail-closed behaviour is confirmed** (decision D, 2026-10-23). An inspection error and an input over 100,000 characters both BLOCK. The explanation states the actual reason ("the text could not be inspected" / "the text is too large to inspect completely"). It names no category and never claims that sensitive information was found; this is tested in `test_fail_closed_on_error_oversize_and_empty`. Both are single settings in `configs/inference/policy.json`.

**Security modes** (`configs/inference/policy.json`) change how sensitive the model is, never *what* is protected. Evidence for the selected Round 2 system, R3 (`r2_e3b_positive`) + rules v3, from the full pipeline on `dev_v1` (56 BLOCK / 75 ALLOW; `reports/history/ROUND2_REPORT.md` §8):

| Mode | Decoding | `dev_v1` False ALLOW | `dev_v1` False BLOCK |
|---|---|---|---|
| **`strict`** (default, recommended) | argmax + rules | 0 / 56 (95% CI 0–6.4%) | 27 / 75 (36%) |
| `maximum` | token threshold 0.05 + rules | 0 / 56 | 32 / 75 (43%) |

* On `dev_v1`, `maximum` adds 5 false blocks and shows no leakage benefit, because `strict` already has none there.
* On report-only synthetic sets `maximum` does reduce leakage: format-shifted values 45 → 20 of 3,055; long documents 2 → 0 of 45.
* No point in the `dev_v1` operating-point table lowers false blocks without giving up leaks (`reports/evidence/operating_points_r2_e3b_positive__rules_v3_dev_v1.json`).
* **The independent benchmark confirms it** (`challenge_v2`, `reports/FINAL_REPORT.md` §5–6):

  | Mode | False ALLOW | False BLOCK | Entity recall |
  |---|---|---|---|
  | `strict` | 2/200 | 70/200 | 0.898 |
  | `maximum` | 1/200 | 78/200 | 0.898 |

  `maximum` gives no measurable leakage benefit for more friction.

**Mode decision (final).**
* **`strict` is the product mode.** The application and any API pass `"strict"` explicitly.
* **`maximum` is retained** in the code and in `configs/inference/policy.json` for reproducibility and research. It is **not exposed as a user-facing option**, and a mode is never taken from user input (`docs/INTEGRATION.md` §2.2).

No false-block "budget" has been invented: the table gives the evidence, and the product owner chooses.

**Explanations** name the categories, their counts and character positions, and never values. Even value *shapes* are withheld, because a password's length and character classes are themselves sensitive. Logs carry the decision, reason, mode, categories, counts, input length and latency; tests verify that neither logs nor outputs contain the inspected values.

## 6. Security vs usability: what the evidence says so far

* After Round 2, the selected system (R3 + rules, `strict`) has 0/56 False ALLOW and 27/75 False BLOCK on the hand-written `dev_v1`. That is fewer leaks than the Round 1 system (5/56) and about the same false blocks (28/75).
* Almost every false block is on harmless identifiers: tracking, order and meeting IDs, versions, SKUs, error codes, arithmetic. On `dev_v1`, 33 of R3's 34 false-block findings come from the model, not the rules.
* **Thresholds cannot remove these false blocks.** 68% of R3's false-positive spans on `dev_v1` score ≥ 0.9, and 83% on the held-out hard-negative families (`reports/evidence/calibration_r2_e3b_positive.json`).
* The hard-negative data of Round 2 (experiments R2 and R4) does remove most of them. R4 has 12/75 False BLOCK on `dev_v1`. But R2 alone increased leakage, and the selection rule fixed in advance therefore did not allow R4 (`reports/history/ROUND2_REPORT.md` §7). Choosing usability over that rule is a product decision; it has not been made.
* The public-figure policy (§3) adds intended blocks that users may experience as friction. They are reported separately and never counted as errors.
* **On the independent `challenge_v2`** (400 cases by a separate author), `strict` has False ALLOW 2/200 and False BLOCK 70/200 (35%). 64 of the 70 false blocks are on look-alike cases. The trade-off measured on `dev_v1` holds on independent text.
* No real employee prompts have been evaluated. Every rate above comes from synthetic, hand-written or independently authored data (see `docs/RISKS.md`).

## 7. Privacy of the detector itself

* Everything runs in-process; no text is sent to any service.
* Model weights are loaded from a local directory with `local_files_only=True`.
* Reports and metrics files contain counts, character-class shapes (for synthetic evaluation data only) and offsets.
* The `challenge_v2` tooling never prints case text.
