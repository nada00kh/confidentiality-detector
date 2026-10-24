# What is proven, what is not, and what remains risky

Status after round 1 and round 2 (both executed; round 2 verified and analysed in `reports/ROUND2_REPORT.md`).

## 1. Proven by executed experiments

* **The original 0.9925 F1 was a measurement artefact.**
  * Reproduced exactly; corrected validation F1 0.643, precision 0.476.
  * The original model blocks 74.5% of documents containing no target entity (`reports/ROUND1_REPORT.md` §2).
* **Fixing the labels alone raised realistic leakage.** E1 versus the original model on `challenge_v1`: FAR 19.6% vs 9.8%, p = 0.004.
* **Format augmentation generalises.** E2 reached FAR 2.8% on held-out formats and 7.6% on `challenge_v1`, versus 10.5% and 19.6% for E1 (p < 0.001 and p = 0.003).
* **The hybrid (E2 + rules) is the best measured system:**
  * `challenge_v1` FAR 2.2% (95% CI 0–5.4%), FBR 18.3% (8–28%);
  * held-out formats FAR 2.2%;
  * it beats the original model on both error types.
* **Most realistic false positives are high-confidence.** About two thirds of false-positive spans score ≥ 0.9, so thresholds cannot remove them (`reports/calibration_e2_mbert_v2_fmtA.json`).
* **Round 2 (verified from the archived predictions; `reports/ROUND2_REPORT.md`):**
  * The selected system, R3 (`r2_e3b_positive`) + rules v3 in `strict` mode, leaks less than E2 + rules: `dev_v1` False ALLOW 0/56 vs 5/56 (exact McNemar p = 0.06); held-out formats 45 vs 61 of 3,055 (p = 0.014). False BLOCK is unchanged: 27/75 vs 28/75.
  * Hard negatives alone (R2) cut false blocks sharply, but also suppressed genuine difficult positives: `synth_B_heldout` False ALLOW 0 → 26.
  * Combining A + B (R4) keeps leakage at R1's level and cuts `dev_v1` False BLOCK to 12/75.
  * Long-document errors have two measured causes; neither is truncation or a merging error (every model input is ≤ 512 tokens, and every token is predicted exactly once).
    * The Round 1/2 stitching predicts the last tokens before each window cut with no right context. Those 4.3% of tokens hold most of the errors that do not occur on the same text in isolation.
    * 99.7% of supervised training tokens sit at window positions 0–127, so positions ≥ 128 are barely fine-tuned.
* **Pipeline correctness, checked by 125 automated tests:**
  * alignment reproduces the original tokenised dataset;
  * windowed inference handles entities across window boundaries;
  * policy fails closed;
  * no values appear in outputs or logs;
  * Colab runs fail loudly;
  * stored predictions are refused on a changed evaluation file;
  * the case-file and `challenge_v2` tooling hold no text.

## 2. Not proven

* **Real-world performance.** No genuine, governed employee prompts were ever evaluated. Every number comes from synthetic data or from text written by the project engineer. Nothing here is a real-world validation.
* **Independent generalisation of the current system.** `challenge_v1` and `dev_v1` were written by the same engineer who wrote the rules and the generators, so shared assumptions inflate both. `challenge_v1`'s failures have been studied, so it is now a regression set. Independent evidence will only exist once `challenge_v2` is evaluated.
* **That R3's advantage holds on independent text.** It rests on `dev_v1` (56 BLOCK cases, 0 vs 5 leaks, p = 0.06) and on synthetic held-out formats. `dev_v1` has now been used for one model selection, so reusing it for further selections would overfit it.
* **`synth_B_heldout` as evidence for B-trained models.** Its families are held out, but 20% of its target values (235/1,192: names, usernames, CVVs) also occur in `B_train`, because both come from the same generator value pools. It measures generalisation to unseen templates, partly with memorised values.
* **Whether shorter inference windows fix long inputs.** This is prepared (`scripts/window_study.py`, rule in `docs/METHODOLOGY.md` §7) but not run: it needs the checkpoint locally.
* **Stability.** One seed per configuration. In-distribution differences of 0.1–0.5 points are within noise.
* **Latency on target hardware.** Only measured on one laptop CPU.

## 3. Known weaknesses (measured)

* **False blocks on harmless identifiers: the main remaining weakness of the selected system.** Tracking, order and meeting IDs, versions, SKUs, error codes and arithmetic:
  * `dev_v1` False BLOCK 27/75 (36%, 95% CI 26–47%);
  * the held-out hard-negative families 664/960 (69%).
  * 33 of 34 findings come from the model, at high confidence, so no threshold removes them.
  * The R4 recipe removes most of them (12/75; 187/960), but was not eligible under the selection rule fixed in advance.
* **Misses that leave the document blocked only by luck.** Lowercase or context-free names, lowercase usernames, and passwords inside JSON/SQL. In 10 of 92 `challenge_v1` BLOCK documents a sensitive value was missed while another one triggered the block. Experiment B and the v3 rules address this.
* **CVV without a literal cue.** Ambiguous by policy unless context supports it. A bare 3–4 digit number is deliberately not blocked.
* **Version numbers that are valid IPv4 addresses** ("firmware 2.4.1.7"). The rules suppress them with version context and with the small-first-octet heuristic, but context-free cases remain ambiguous. The IPv4 validation gate would remove the model's version-string false positives (`synth_A_heldout` False BLOCK 664 → 606). It stays off because it also discards model detections of spaced or mistyped addresses (`docs/METHODOLOGY.md` §8).
* **Non-canonical IPv4 formats** (fictional probe, `reports/ipv4_gate_study.json`; no evaluation set contains them):
  * defanged addresses (`203[.]0[.]113[.]9`, `(dot)`) and comma-separated octets are **not detected** (False ALLOW);
  * leading-zero and hostname-encoded addresses are blocked, but under the wrong label (PHONENUMBER, SSN).

  Security tickets and incident notes are where these forms appear.
* **Long documents.** Tokens before a window cut get no right context, and the model is barely fine-tuned for window positions ≥ 128. The window study (`docs/METHODOLOGY.md` §7) found that neither centered stitching nor shorter windows changed any decision on `validation_long`, so the Round 2 setting (512 / 64 / first) is retained. On the report-only `test_long` (2-window documents of 598–942 tokens), shorter centered windows looked better (False ALLOW 2 → 1, False BLOCK 5 → 3). That set cannot be used to select, and a larger long-document validation set is future work. With the retained setting, R3 has False ALLOW 2/45 and False BLOCK 5/28 on `test_long`. Real enterprise prompts (pasted logs, e-mail threads, reports) are often this long.
* **Public-figure names are blocked by policy.** This is an intended cost, but it adds user friction (`docs/POLICY.md` §3).
* **Out-of-scope secrets** (API keys, tokens) are not protected. Under decision F, a detector that calls them PASSWORD is charged a false positive and, on an otherwise clean document, a False BLOCK. R0–R2 do this on `challenge_v1` `code-013`; R3 and R4 do not in `strict` mode. Only one such case exists in the hand-written sets, so this behaviour is essentially unmeasured; `challenge_v2` requires an `oos-secret` tag.

## 4. Dataset limitations

* **Synthetic data.** ai4privacy is LLM-generated with unrealistic values: 10% of its card numbers pass Luhn, and half its SSNs have 11 digits. The context cues are strong, and 96–98% of names repeat across splits.
* **Narrow coverage in the round-2 generator.** Families are diverse in frame but still template-based (142 templates). Held-out *families* test template generalisation, not open-world language.
* **Annotation conventions.** STREET excludes the house number. MIDDLENAME, MASKEDNUMBER and CVVs without evidence are ignored, so behaviour on them is unmeasured.
* **English only.** The model is multilingual, but no other language was evaluated.

## 5. Security risks of the system itself

* **Adversarial evasion is out of scope.** A user who deliberately splits, encodes or obfuscates values (zero-width characters, homoglyphs, spelled-out digits, base64) will usually get through. The design target is *accidental* disclosure.
* **Fail-closed behaviour depends on integration.** BLOCK on error or oversized input only protects if the calling application honours the decision and does not fall back to sending the prompt when the checker is unavailable.
* **Model files are trusted inputs.** Load checkpoints only from the organisation's controlled storage. Loading verifies key completeness and the label mapping, but not provenance or signatures.
* **Logs** carry categories and offsets. Offsets plus the original text would locate the values, so the original text must not be logged next to them.

## 6. Before considering real deployment

1. ~~Run round 2 and apply the pre-registered selection rule.~~ Done: R3 + rules v3, `strict` recommended (`reports/ROUND2_REPORT.md`). Remaining before the hidden benchmark: download the R3 checkpoint, optionally run the window study (§7 rule), and freeze the system (`scripts/challenge_v2.py freeze --verify-pred-dir …`).
2. Evaluate once on the independent `challenge_v2`, and report it as is.
3. **Evaluate on a governed sample of real prompts**, collected with consent and a privacy review, annotated by two people under `docs/ANNOTATION_GUIDELINES.md`, with inter-annotator agreement measured.
4. Shadow deployment: log decisions only (no text) without blocking, and measure the block rate and user-reported false blocks.
5. Repeat training with ≥ 3 seeds for the selected configuration and report the variance.
6. Integration review: fail-closed handling, latency budget on target hardware, model storage and access control, a monitoring dashboard built on value-free logs.
7. A product decision on the operating point and on public-figure friction, informed by steps 3–4.
