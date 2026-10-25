# Challenge v2 — Independent Author Handoff Specification

Version 1.0, 2026-10-24. Prepared from the project repository at commit `5e7050b`. The detection system was frozen at code commit `4907107`.

This document consolidates every normative requirement for `challenge_v2` from:
* `docs/CHALLENGE_V2_SPEC.md`, `docs/CASE_FORMAT.md`, `docs/ANNOTATION_GUIDELINES.md`, `docs/POLICY.md`;
* the code that will read your file: the case parser `src/confidentiality_detector/challenge.py`, and the validator, sealer and evaluator `scripts/challenge_v2.py`.

Where the older documents and the code differ, **the code is what will score your file**. Those differences are listed in §12.

**Requirement levels used below**

| Marker | Meaning |
|---|---|
| **[Required]** | Enforced by the parser or validator. A violation is an error, or it silently corrupts the file (stated where so). |
| **[Policy]** | Established annotation policy of the project. Normative, but not machine-checked. |
| **[Recommended]** | Guidance for a useful benchmark. Not enforced. |

---

## 0. Your role and the rules of independence

* You write and annotate every case. The developers of the detector will **never see your cases**, the detector's output on them, or per-case results.
* Do not base cases on the project's development data. Do not ask anyone to run the detector on draft cases, and do not adjust cases after seeing any detector output.
* The product owner runs the validation, sealing and evaluation tools locally (§6–8). They pass you only validation messages: case ids, categories and error types, never other people's text.
* The frozen system is evaluated **once**. If it were changed in response to the results, `challenge_v2` would stop being an independent test.
* **[Policy] All values must be fictional.** Never use real personal data, real credentials or real account numbers:
  * invent names (real public figures are allowed, §3.4);
  * use 555-01xx phone numbers;
  * use card numbers that pass the Luhn check but are not real cards (generated or public test numbers);
  * use IBANs with valid checksums but no real account (generated or published specimens);
  * use made-up passwords, usernames and e-mail domains.

## 1. File format (authoritative schema)

### 1.1 The file

* **[Required]** One plain-text file containing all cases, in **UTF-8 without a byte-order mark (BOM)**. A BOM makes the parser miss the first case header, so the first case is silently lost.
* Line endings may be LF or CRLF; the text is normalised to LF.
* It is not JSON or JSONL. Text and gold annotations are stored **together**, as inline markup.
* Lines before the first case header are a free preamble and are ignored. Put any notes there.

### 1.2 Case header

**[Required]** Exactly one line per case:

```
@@ <CASE_ID> | <TAGS> | <DECISION>
```

* `<CASE_ID>` contains letters, digits, `_` or `-` only, and is **unique in the file**; a duplicate id is an error. **[Recommended]** use ASCII ids such as `c2-0001`.
* `<TAGS>` is a comma-separated list with **no spaces**. Each tag contains letters, digits, `_` or `-`. An empty list is allowed but produces a warning.
* `<DECISION>` is exactly `BLOCK`, `ALLOW` or `AMBIGUOUS`, in **upper case**. It is required on every case; a missing decision is an error.
* Spaces around `|` are allowed. Nothing may follow the decision.
* **[Required] A header that does not match this grammar is not reported.** That includes a space in the tag list, a lowercase decision, or an extra field. The line, and the whole case under it, silently become text of the **previous** case. After validation, confirm that the reported number of cases equals the number you wrote.
* The parser adds the decision in lower case (`block`, `allow`, `ambiguous`) to each case's tags for per-tag reporting.
* No other metadata fields exist. Explain an ambiguity through a `~TYPE` name or a tag.

### 1.3 Case text

* A case's text runs from the line after its header to the line before the next header.
* Leading and trailing blank lines are removed. Blank lines inside a case are kept. Trailing spaces on a line are kept.
* **[Required] Line-level pitfalls:**
  * A line beginning with `# ` placed **directly after the header**, before any text line, is dropped. A case must not begin with such a line.
  * Any line consisting of `#` followed by three or more `-` or `=` (for example `# ======`) is dropped, wherever it appears, including inside a case.
  * Any other line between two cases belongs to the previous case's text. That includes a `# comment` line after a separator. Do not put comments between cases; use the preamble.
  * The text must not contain the character sequences `[[` or `]]` other than as annotation markup. That is an error, so nested-list code such as `[[1, 2]]` or TOML `[[table]]` headers cannot appear verbatim.
  * A text line that itself matches the header grammar starts a new case.

### 1.4 Inline annotations

| Markup | Role | Scoring |
|---|---|---|
| `[[LABEL:value]]` | target entity; `LABEL` is one of the 13 labels (§2) | gold entity; the case must be BLOCK |
| `[[!TYPE:value]]` | out-of-scope look-alike (hard negative), for example `!TRACKING`, `!VERSION`, `!APIKEY` | any detector prediction on it is a false positive |
| `[[~TYPE:value]]` | genuinely ambiguous span, for example `~AMBIG` | predictions on it are neither rewarded nor penalised |

* **[Required] Labels.** Target labels are matched case-insensitively and stored in upper case; any label outside the 13 is an error. `TYPE` after `!` or `~` is free-form: letters, digits, `_` and `-`, upper case recommended.
* **[Required] Values:**
  * at least one character, on **one line**; a value cannot span lines;
  * no `]]` inside; avoid values that end in `]`;
  * may contain `:`, because only the first `:` separates label and value;
  * a target value must not start or end with whitespace (error).
* **The value is the text.** Markup is removed and the value stays verbatim.
* **[Required] No nesting.** Target spans can never overlap; adjacent annotations are fine.

### 1.5 Offsets

You never write offsets. The parser computes each span as `start` and `end` indices over the final case text: after markup removal and LF normalisation, counted in Unicode characters (code points), with `end` **exclusive**. Any Unicode text is allowed.

### 1.6 Schema-only template

```
<optional preamble: any lines before the first header are ignored>

@@ <CASE_ID> | <TAG_1>,<TAG_2> | <BLOCK|ALLOW|AMBIGUOUS>
<case text> [[<TARGET_LABEL>:<VALUE>]] <case text> [[!<LOOKALIKE_TYPE>:<VALUE>]] <case text>
<further lines of the same case> [[~<AMBIGUITY_TYPE>:<VALUE>]]

@@ <CASE_ID> | <TAG_1> | <BLOCK|ALLOW|AMBIGUOUS>
<case text>
```

## 2. The 13 target labels (exact names)

`PASSWORD`, `USERNAME`, `EMAIL`, `PHONENUMBER`, `FIRSTNAME`, `LASTNAME`, `SSN`, `CREDITCARDNUMBER`, `CREDITCARDCVV`, `IBAN`, `ACCOUNTNUMBER`, `STREET`, `IPV4`.

No other target label exists, and none may be added.

## 3. Annotation rules

### 3.1 General span rules [Policy]

* **The value only.** Exclude surrounding quotes, brackets and trailing punctuation (`.` `,` `;` `)`), unless the character belongs to the value; a password ending in `!` keeps the `!`.
* **Keep internal separators** (spaces, dashes) in card numbers, IBANs, phone numbers and account numbers.
* **No target inside another target.** Annotate the outer category only:
  * a name inside an e-mail address is part of the EMAIL;
  * in a URL credential, the user part is USERNAME and the part after the colon is PASSWORD;
  * a path segment `/home/<user>/` is a USERNAME.
* **One span per name token.** A given name and a family name are two spans, FIRSTNAME and LASTNAME. Exclude titles (Mr., Dr.).
* **Placeholders are not values:** `<password>`, `{{email}}`, `********`, `your-password-here`, `XXXXX-XXXXX`.
* **Partial or masked values** ("ending 1881", `**** 1234`) are not CREDITCARDNUMBER. Mark them `!PARTIALCARD` if useful.
* A complete value cut off by the end of the text is annotated over the part that is present.

### 3.2 Per-label rules [Policy]

| Label | Annotate | Do not annotate (look-alike `!` or ambiguous `~`) |
|---|---|---|
| FIRSTNAME / LASTNAME | identifiable person names in any capitalisation, **including famous people**, in prose, greetings, signatures, e-mail headers and SQL/CSV/JSON fields | company, product and place names (`!COMPANY`, `!PRODUCT`); ordinary words (May, Will, Grace); fictional characters (`~AMBIG`); middle names (`~`); single-word names (see §11) |
| USERNAME | login names and handles: after `username`, `login`, `user=`, `User Id=`; `ssh u@host`; `/home/u/`; `CREATE USER u`; `psql -U u`; "logged in as u"; `@u` mentions; service accounts such as `svc_backup` | the local part of an e-mail (part of EMAIL); generic system accounts such as `root`, `admin` (`~AMBIG`); display names that are person names (FIRST/LAST) |
| PASSWORD | the secret value of an account password or passphrase, wherever it appears: prose, JSON/YAML/SQL/env/CLI, connection strings, `.netrc`, alphanumeric passcodes | the word "password"; placeholders; **API keys, access tokens, private keys, webhook secrets** (`!APIKEY`, `!TOKEN`, …, never `~`; §3.5); numeric door, locker or meeting codes (`!PIN`) |
| EMAIL | the full address, including `+tag` and sub-domains | — |
| PHONENUMBER | the full number, with country code, parentheses and separators | an extension written as words ("ext. 4417") stays outside the span |
| SSN | **US** social security numbers, dashed, or undashed with a cue | EIN, DUNS, vendor numbers (`!COMPANYID`) |
| CREDITCARDNUMBER | the full card number (13–19 digits) with its separators | partial or masked numbers; IMEIs; 13-digit barcodes (`!SKU`) |
| CREDITCARDCVV | 3–4 digits **with evidence** (§3.4) | isolated short numbers; one-time codes; PINs; "security code" without card context (`~AMBIG` if unsure) |
| IBAN | the IBAN, grouped or compact | BIC/SWIFT (`!BIC`); sort and routing codes (`!ROUTING`) |
| ACCOUNTNUMBER | bank and financial account numbers, with their separators | order, invoice, ticket, customer-reference and vendor numbers |
| STREET | the street name **with** its suffix ("Elm Street"); **the house number is excluded** | city, state, ZIP; unit or flat numbers |
| IPV4 | any **host** IPv4 address, including private ranges | version numbers in version context (`!VERSION`); CIDR ranges, loopback (127.0.0.1) and netmasks (`~AMBIG`) |

### 3.3 Person names [Policy]

* A clearly identifiable person's given name is FIRSTNAME and family name is LASTNAME, **whether or not the person is famous**. There is no exemption for public figures.
* A harmless public-information request that names a real person is therefore a **correct BLOCK**.
* Company, product and place names and ordinary words are not person names, even when they look like one.
* Fictional characters are name-shaped but not persons: mark them `~AMBIG`.

### 3.4 CVV evidence (exact rule) [Policy; the validator warns]

A 3–4 digit value is CREDITCARDCVV only if at least one of the following holds; otherwise mark it `~AMBIG` (if a reader could take it for a CVV) or leave it unannotated.

1. **A strong cue** appears within 60 characters before or 40 characters after the value: `CVV`, `CVV2`, `CVC`, `CVC2`, `CCV`, `CSC`, `CVN`, "card verification" (optionally followed by value/code/number), "digit(s) on the back", or "back of the/your/my/this card".
2. **Card context** lies within 120 characters on either side: a card number (13–19 digits, optionally separated by spaces or dashes) or an expiry date ("exp", "expiry", "expiration", "expires", "valid thru/through/until", or `MM/YY`, `MM/YYYY`).
3. **The weak cue "security code"** appears within those 60/40 characters **and** a card word appears within 120 characters: card, visa, mastercard, amex, american express, discover, credit, debit.

"Security code" alone is not enough. It also names one-time codes and PINs.

### 3.5 Out-of-scope categories [Policy]

These are **not** among the 13 categories. A case containing only them is **ALLOW**.
* **Credentials:** API keys, access and authentication tokens, private keys, webhook and client secrets. Annotate them as look-alikes, `[[!APIKEY:…]]` or `[[!TOKEN:…]]`. **[Required]** Never use `~SECRET`, `~APIKEY`, `~TOKEN`, `~JWT`, `~PRIVATEKEY` or similar: the validator rejects them. Look-alike annotation is what makes a detector that calls a key a PASSWORD count as a false positive, and as a False BLOCK on an otherwise clean case.
* **Codes:** one-time codes, meeting passcodes, door and locker PINs.
* **Device and network identifiers:** IPv6, MAC addresses, IMEIs, crypto addresses.
* **Bank codes:** BIC/SWIFT, routing and sort codes.
* **Business identifiers:** order, ticket, invoice, tracking, customer-reference and similar numbers.

### 3.6 Look-alikes that must remain ALLOW [Policy; markup recommended]

Harmless values that look sensitive are not targets:
* order, tracking, invoice and ticket numbers;
* meeting IDs, versions and builds, error codes;
* part, serial and SKU numbers;
* arithmetic, dates, prices;
* short numbers in ordinary context (room 482, page 204, port 5432).

**[Recommended]** mark each one with `[[!TYPE:…]]`, for example `!TRACKING`, `!VERSION`, `!ORDERID`, `!SKU`, `!ERRORCODE`, `!PIN`.

### 3.7 Malformed, mistyped or invalid values

* **[Policy]** Annotate by **meaning in context**, not by checksum. The project's security policy is that a failed checksum or a mistyped digit must not let a possibly sensitive value through: the product owner rejected detector gates that drop values with invalid IBAN, card or SSN checksums. A value that the text clearly presents as a person's card number, IBAN or SSN is annotated as such even if its checksum fails.
* **[Required]** The validator warns about every failed Luhn or IBAN mod-97 check ("intended?"). Confirm each one is deliberate.
* **[Recommended]** Use valid checksums by default, and make invalid ones a deliberate minority (for example tagged `mistyped`).

### 3.8 Addresses [Policy]

Only the street name with its suffix is a target (STREET). House numbers, unit numbers, city, state, ZIP and country are not.

### 3.9 IPv4 [Policy, with §11 for unusual notations]

* A **host** IPv4 address is IPV4, including private ranges.
* Network ranges (CIDR), loopback and netmasks are `~AMBIG`.
* A version number that happens to have IPv4 shape is `!VERSION` when the context says version, build or firmware. Without context it is genuinely ambiguous (`~AMBIG`).

### 3.10 Gold labels are independent of any detector [Policy]

Annotate what the policy says, never what you expect a detector to output. Do not avoid, favour or reshape cases based on guesses about detector behaviour. Write realistic text for the categories and tags in §5.

## 4. Document decision rules

* **[Required]**
  * **BLOCK** requires at least one target annotation.
  * **ALLOW** and **AMBIGUOUS** require none: any target means BLOCK. An inconsistent decision is an error.
* **[Policy]**
  * **BLOCK** if the case contains at least one protected value.
  * **ALLOW** if it contains none. This includes cases with only look-alikes or out-of-scope credentials.
  * **AMBIGUOUS** only if you cannot honestly say whether the case should be blocked.
* **[Required] Your decision is the gold label.** A case marked ALLOW that contains `~` spans is scored as ALLOW, so a detector that blocks it is charged a False BLOCK. If the ambiguous value would make blocking reasonable, mark the case AMBIGUOUS instead.
* AMBIGUOUS cases are excluded from document-level metrics; their number is reported. A detector prediction inside an AMBIGUOUS case that falls outside its `~` spans still counts as an entity-level false positive.
* A case with no target entity is an ordinary ALLOW case. **[Recommended]** never leave a case's text empty.

## 5. Dataset composition

* **Size [Recommended; the validator warns below the minimum]:** at least **100 BLOCK and 100 ALLOW** cases; 150 or more of each is better. A few AMBIGUOUS cases are fine.
* **Content [Recommended]:** realistic text an employee might paste into an AI assistant:
  * requests;
  * e-mails and chat threads;
  * support tickets;
  * code, configuration, logs and SQL;
  * JSON, CSV and YAML;
  * form data;
  * meeting notes and long documents.
* **Coverage tags [Recommended: each tag at least 10 times, with BLOCK and ALLOW cases mixed within each tag; the validator warns only when a tag is entirely absent]:**

| Tag | Meaning |
|---|---|
| `enterprise` | ordinary workplace communication (e-mails, chats, tickets, reports) |
| `lookalike` | harmless identifiers that look sensitive (§3.6) |
| `structured` | JSON, YAML, SQL, CSV, logs, config files, tables, command lines |
| `difficult-positive` | sensitive values that are easy to miss: lowercase names, names without context, usernames without "username:", passwords inside code or data, unusual phone/IBAN/account formats |
| `unfamiliar-format` | formats a detector may not have seen (other countries' numbers, unusual separators) |
| `long` | documents of roughly 500 words or more, with the sensitive value anywhere, or nowhere, including far from the start |
| `oos-secret` | API keys, access tokens, private keys, webhook secrets, annotated `!APIKEY` / `!TOKEN` (ALLOW unless another protected value is present) |

  Finer tags of your own (`cvv`, `public-figure`, `sql`, `mistyped`, …) are welcome.
* **Length [Required, as a constraint of the system being tested]:** keep every case well under **100,000 characters**. Longer inputs are blocked by policy as "too large to inspect", whatever they contain.

## 6. Validation (run by the product owner)

From the repository root, in Windows PowerShell:

```powershell
. .\scripts\dev_env.ps1
python scripts/challenge_v2.py validate data/challenge_v2/challenge_v2.txt
```

* **Where to keep the file:** `data/challenge_v2/` is excluded from Git and refused by the project's bundle builder. A folder outside the repository also works.
* **What it checks:**
  * **Errors:** header grammar, unique ids, known target labels, no leftover `[[`/`]]`, decision present and consistent with the annotations, no `~` on out-of-scope credentials, no whitespace at target-span edges.
  * **Warnings:** CVV without evidence (§3.4), failed IBAN/Luhn checksums, missing tags, fewer than 100 BLOCK or ALLOW cases, an absent coverage tag.
* **Order of errors.** Structural errors stop validation at the **first** one: unknown label, leftover markup, a decision inconsistent with the annotations, overlapping targets, duplicate ids. Fix it and re-run. Content checks (missing decision, `~` on credentials, span whitespace, and all warnings) are listed together.
* **What it prints:** counts (cases, decisions, labels, tags), the file's sha256, then up to 50 errors and 50 warnings. These name only case ids and categories, never text. The exit code is 0 without errors and 1 with errors.
* **Confirm the count.** The reported number of cases must equal the number written (§1.2).

## 7. Sealing (run by the product owner, after the author confirms the final file)

```powershell
python scripts/challenge_v2.py seal data/challenge_v2/challenge_v2.txt
```

* **Refusal:** sealing refuses a file with validation errors.
* **The seal file:** `reports/challenge_v2/SEAL.json` contains the file name, the file's **sha256**, the sealing time, the number of cases, the decision counts and the label counts. It contains no text.
* **Verifying the seal:** there is no separate verify command. `evaluate` and `contamination` recompute the sha256 and refuse a file that differs. A manual check is to compare the sha256 printed by `validate` with `SEAL.json`.
* **Re-sealing:** running `seal` again overwrites `SEAL.json`. Seal only the final version; every evaluation records the sealed file's sha256 in the ledger.
* **Optional, after sealing:**

  ```powershell
  python scripts/challenge_v2.py contamination data/challenge_v2/challenge_v2.txt
  ```

  It reports, as aggregates only, how similar the cases are to the detector's training data: median maximum TF-IDF cosine, share ≥ 0.5, share ≥ 0.8, and maximum.

## 8. Final evaluation (once; run by the product owner)

Pre-declared protocol: **`strict` is the primary result and `maximum` is a secondary result.** Each mode is evaluated once, strict first.

```powershell
. .\scripts\dev_env.ps1
python scripts/challenge_v2.py verify-frozen --model-dir checkpoints/r2_e3b_positive
python scripts/challenge_v2.py evaluate data/challenge_v2/challenge_v2.txt --model-dir checkpoints/r2_e3b_positive --mode strict
python scripts/challenge_v2.py evaluate data/challenge_v2/challenge_v2.txt --model-dir checkpoints/r2_e3b_positive --mode maximum
```

* **Frozen-system check:** `verify-frozen` uses no challenge data. It re-checks the frozen system's identity and behaviour.
* **Refusals:** `evaluate` refuses an unsealed or modified file, and any system that differs from the frozen record. That covers checkpoint files, policy, inference code, windows and runtime library versions.
* **Results:** each run writes `reports/challenge_v2/result_r2_e3b_positive_<mode>.json` (aggregates only).
* **Ledger:** each run appends a line to `reports/challenge_v2/LEDGER.jsonl`. It records the time, the challenge sha256, the frozen-system identity, the mode, the False ALLOW and False BLOCK rates, and a fingerprint of the predictions (ids, positions and labels hashed; no text).
* **The second run's note is expected.** The `maximum` run prints "evaluated 2 times", because the ledger counts every evaluation; with the declared protocol that is not a problem.
* **Per-case outcomes (`--case-details <path>`):** case id, tags, gold and predicted decision, missed and extra categories; never text. They are for the author only. Write them outside the repository, and never give them to the developers.
* **What goes to the developers:** `SEAL.json`, `LEDGER.jsonl` and the two `result_*.json` files, and nothing else. The case file stays with the author and the product owner.

## 9. Metrics in the result file

* **Document level:**
  * BLOCK is the positive class, and the system's actual BLOCK/ALLOW decision is scored, including fail-closed blocks.
  * **False ALLOW:** gold BLOCK, predicted ALLOW. Its rate is over gold-BLOCK cases.
  * **False BLOCK:** gold ALLOW, predicted BLOCK. Its rate is over gold-ALLOW cases.
  * Both rates come with **95% Wilson confidence intervals**.
  * Also reported: BLOCK precision, recall and F1; accuracy; the confusion matrix; the numbers of BLOCK, ALLOW and excluded AMBIGUOUS cases.
* **Entity level:**
  * **Exact match:** start, end and label must all match. Micro precision, recall and F1, with TP/FP/FN counts.
  * **Per label:** precision, recall, F1 and support, plus *overlap recall* (a same-label prediction overlaps the gold span) and *caught as any type*.
  * **Error breakdowns:** false negatives as boundary, type confusion or missed; false positives as boundary, type confusion, on a look-alike, or spurious.
  * Predictions inside `~` spans are not counted; predictions on `!` spans are false positives.
* **Subgroups:**
  * per tag: case counts, False ALLOW, False BLOCK;
  * per length: ≤ 1,000, 1,001–3,000 and > 3,000 characters;
  * the share of BLOCK cases in which every gold entity was caught.
* **Not reported by the frozen evaluator:**
  * relaxed (overlap) precision and F1;
  * macro F1 (derivable from the per-label results);
  * false positives broken down by individual look-alike TYPE (only the total on look-alikes; per-tag False BLOCK counts are available);
  * confidence intervals at entity level.
* **No automatic checks** for duplicate texts or for overlap with the development sets. The contamination command (§7) measures similarity to the training data only. **[Recommended]** avoid duplicate or near-duplicate cases.

## 10. Technical constraints (checklist)

* UTF-8 without BOM; header grammar exactly as §1.2; unique ids; decision in upper case.
* No comment lines between cases; no case starting with a `# ` line; no `#---` or `#===` lines inside case text.
* No literal `[[` or `]]` in text; annotation values on one line, without `]]`.
* Only the 13 target labels; free-form `!TYPE` and `~TYPE`; never `~` on credentials.
* Decision consistent with the annotations; no whitespace at target-span edges.
* Each case well under 100,000 characters, and never empty.
* After validation, the case count equals the number written.

## 11. Known ambiguities requiring annotation judgment

Where the policy is explicit, follow it. Where it says "judgment", choose, record the choice in a tag or a `~TYPE` name, and apply it consistently.

* **Public figures [Policy]:** names, so BLOCK. **Fictional characters [Policy]:** `~AMBIG`.
* **Single-word names (mononyms):**
  * The policy says such a name blocks the case but is not scored by entity type.
  * **[Required] The format cannot express that.** A BLOCK case needs at least one target annotation, and a case whose only annotation is `~` cannot be BLOCK.
  * **Until the product owner decides otherwise:** do not write cases whose *only* protected value is a mononym. Where a mononym appears next to another protected value, annotate it `[[~MONONYM:…]]`.
* **Multi-word family names** (for example a particle plus a surname): one span per whitespace token is the documented rule ("one span per name token"). Annotate each token as LASTNAME (judgment).
* **Generic accounts** `root`, `admin` [Policy]: `~AMBIG`.
* **Short numbers [Policy]:** a 3–4 digit number without CVV evidence is not a CVV (§3.4), and "security code" alone is not enough. Use `~AMBIG` only where a reader could reasonably take it for a CVV.
* **Numeric PINs and passcodes:**
  * numeric door, locker or meeting codes are `!PIN` [Policy];
  * alphanumeric passcodes for accounts are PASSWORD [Policy];
  * a numeric account PIN for a banking login is not addressed explicitly (judgment; the recommendation is `~AMBIG`).
* **National identifiers of other countries:** SSN means **US** social security numbers [Policy]. Other national identifiers are outside the 13 categories. **[Recommended]** mark them `!NATIONALID`, so the case is ALLOW unless another protected value is present.
* **Domestic bank account versus IBAN:** an IBAN is IBAN, and a domestic bank or financial account number is ACCOUNTNUMBER [Policy]. Customer, order and vendor numbers are not targets.
* **Street names without a suffix, or written unusually** (judgment): annotate when the text clearly presents a street address; mark `~AMBIG` if unsure. The house number is always excluded [Policy].
* **IPv4 in unusual notations** (spaces around dots, `[.]` or `(dot)` defanging, leading zeros): the policy covers "any host IPv4 address" but does not discuss notation (judgment). **[Recommended]** annotate IPV4 when the text clearly denotes a host address, tag the case `unfamiliar-format`, and mark the notation in a finer tag. Version-shaped values without context are `~AMBIG` [Policy].
* **Malformed or mistyped values:** by meaning in context (§3.7).
* **Values inside code** (environment files, connection strings, SQL, YAML) follow the same rules as prose [Policy].

## 12. Differences between the older project documents and the frozen evaluator (for transparency)

These were found while preparing this specification. The frozen evaluator's behaviour, described above, is what counts. The developers have not changed any code.

1. **Separators and comments.** `CASE_FORMAT.md` says a case ends at "the next header or separator". In the code a separator line is dropped but does not end the case, so a following comment line joins the previous case's text. A `# ` line directly after a header is also dropped (§1.3).
2. **Silent failures.** A malformed header, or a BOM before the first header, is not reported as an error (§1.1–1.2).
3. **Mononyms.** The annotation guidelines' mononym rule ("ignored for entity scoring, but the document is BLOCK") cannot be represented in a case file (§11).
4. **Values across lines.** The guidelines say values may span lines; the case format cannot express that (§1.4).
5. **Look-alike breakdown.** `CHALLENGE_V2_SPEC.md` promises false positives "broken down by look-alike type"; the frozen evaluator reports only the total on look-alikes (§9).
6. **Coverage thresholds.** The recommended "each tag at least 10 times" and "at least 100 BLOCK and 100 ALLOW" are checked only as warnings, and only "tag absent" is detected (§5).
7. **ALLOW cases with only `~` spans.** The guidelines describe a case whose only annotations are ambiguous as implicitly AMBIGUOUS. With the required decision field, your decision wins, and an ALLOW case with only `~` spans is scored as ALLOW (§4).
