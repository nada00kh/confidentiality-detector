# challenge_v2: specification for the independent author

You are writing the final benchmark for a local confidentiality checker. The checker inspects text an employee is about to paste into an external AI assistant and answers **BLOCK** (the text contains protected information) or **ALLOW**.

The developers will **not** see your cases. Please do not share them, discuss individual cases with them, or base cases on their development data.

## 1. What to write

Realistic text that employees might paste into an AI assistant, such as:
* requests ("rewrite this e-mail…");
* e-mails and chat threads;
* support tickets;
* code, configuration files, logs, SQL;
* JSON, CSV and YAML;
* form data;
* meeting notes and long documents.

**Size:** at least **100 BLOCK and 100 ALLOW** cases; 150 or more of each is better. A few AMBIGUOUS cases are fine.

**Coverage.** Tag each case with at least one of these, and make sure every tag appears at least 10 times:

| Tag | Meaning |
|---|---|
| `enterprise` | ordinary workplace communication (e-mails, chats, tickets, reports) |
| `lookalike` | harmless identifiers that look sensitive: order, tracking, invoice and ticket numbers, meeting IDs, versions, error codes, part and serial numbers, arithmetic, dates, prices, short numbers |
| `structured` | JSON, YAML, SQL, CSV, logs, config files, tables, command lines |
| `difficult-positive` | sensitive values that are easy to miss: lowercase names, names without context, usernames without "username:", passwords inside code or data, unusual phone/IBAN/account formats |
| `unfamiliar-format` | formats you think a detector may not have seen (other countries' numbers, unusual separators) |
| `long` | documents of roughly 500 words or more, with the sensitive value anywhere (or nowhere), including far from the start |
| `oos-secret` | API keys, access tokens, private keys, webhook secrets: out of scope, annotated `[[!APIKEY:…]]`. The case is ALLOW unless another protected value is present; a detector that blocks it is charged a False BLOCK |

Add your own finer tags as you like (`cvv`, `public-figure`, `sql`, …). Mix BLOCK and ALLOW cases within each tag.

**Values must be fictional.** Never use real personal data, real credentials or real account numbers:
* invent names (real public figures are allowed, see §3);
* use 555-01xx phone numbers;
* use card numbers that pass the Luhn check but are not real cards (generated or public test numbers);
* use IBANs with valid checksums but no real account (generated or published specimens);
* use made-up passwords and e-mail domains.

## 2. Format

Use `docs/CASE_FORMAT.md`, with the **decision field required on every case**:

```
@@ c2-001 | enterprise,difficult-positive | BLOCK
can you tell [[FIRSTNAME:maren]] the venue changed
```

## 3. What counts as protected (13 categories)

| Category | Protected | Not protected |
|---|---|---|
| FIRSTNAME / LASTNAME | names of real or plausible people, any capitalisation, **including famous people** | company, product and place names; ordinary words; fictional characters (mark `~AMBIG`) |
| USERNAME | login names and handles (`jdoe`, `svc_backup`, `@zara.q`, `/home/rfarhan/`) | generic system accounts like `root`/`admin` (mark `~AMBIG`) |
| PASSWORD | account passwords and passphrases, wherever they appear | API keys, access tokens, private keys (out of scope: mark `!APIKEY` / `!TOKEN`, **never** `~`); numeric door or meeting codes (`!PIN`) |
| EMAIL | e-mail addresses | — |
| PHONENUMBER | phone numbers | — |
| SSN | US social security numbers | company tax IDs (EIN), DUNS |
| CREDITCARDNUMBER | full card numbers | partial cards ("ending 4242") |
| CREDITCARDCVV | the 3–4 digit card security code **when the text makes clear that is what it is** (CVV/CVC/"security code" with card context/"on the back of the card", or next to a card number or expiry) | a bare 3–4 digit number with no such context: mark `~AMBIG` |
| IBAN | IBANs | BIC/SWIFT, sort and routing codes |
| ACCOUNTNUMBER | bank and financial account numbers | order, customer, invoice and ticket numbers |
| STREET | street name with its suffix ("Elm Street"); **do not include the house number** | city, ZIP |
| IPV4 | host IPv4 addresses, including private ones | version numbers; network ranges such as 10.0.0.0/8, 127.0.0.1 and netmasks (`~AMBIG`) |

Precise span rules are in `docs/ANNOTATION_GUIDELINES.md`. In short:
* annotate the value only, without surrounding quotes or a trailing full stop;
* one annotation per name word;
* no annotation inside another (an e-mail address that contains a name is just EMAIL).

**Document decision:**
* **BLOCK** if the case contains at least one protected value;
* **ALLOW** if it contains none;
* **AMBIGUOUS** if you cannot honestly say whether it should be blocked.

Mark harmless look-alikes with `[[!TYPE:value]]` (for example `!TRACKING`, `!VERSION`, `!ORDERID`). This is optional but very useful: it lets the evaluation say *which* look-alikes cause false blocks.

## 4. Workflow and safeguards

1. Write the file **outside the repository** (or in `data/challenge_v2/`, which is git-ignored and refused by the bundle builder).
2. Validate: `python scripts/challenge_v2.py validate path/to/challenge_v2.txt`. It prints counts, errors and warnings, with case ids only. Fix all errors. Review every warning: CVV without evidence, failed checksums, missing coverage tags.
3. Seal: `python scripts/challenge_v2.py seal path/to/challenge_v2.txt`. This records the file's sha256 in `reports/challenge_v2/SEAL.json`. Any later edit breaks the seal, and evaluation refuses to run.
4. Optional: `python scripts/challenge_v2.py contamination path/to/challenge_v2.txt` reports, as aggregates only, how similar the cases are to the training data.
5. Evaluate the system the developers hand over. They freeze it first: `configs/inference/frozen_system.json` records the weights' sha256, the policy file's sha256, the rules version and the inference windows. Evaluation refuses any other system.

   ```
   python scripts/challenge_v2.py evaluate path/to/challenge_v2.txt --model-dir <checkpoint> --mode strict
   ```

   * The result file `reports/challenge_v2/result_<model>_<mode>.json` contains aggregates only:
     * document False ALLOW and False BLOCK rates with confidence intervals;
     * per-category entity metrics, with false positives broken down by look-alike type;
     * per-tag and per-length error counts.
   * Every evaluation is appended to `reports/challenge_v2/LEDGER.jsonl`, with the system fingerprints and a fingerprint of the predictions (ids, positions and labels hashed; no text), so a re-run can be checked for identical output.
   * Add `--case-details <your own path>` to get per-case outcomes for yourself: case id, tags, decisions, missed or extra categories, never text. Share them with the developers only if you accept that `challenge_v2` then stops being an independent test.
6. Send the developers `SEAL.json`, `LEDGER.jsonl` and the `result_*.json` files, and nothing else.

## 5. What the result means

The result is the system's performance on *your* realistic cases. It is the best available evidence of generalisation, but it is still not a measurement on real employee traffic. If the developers change the system in response to it, a new independent set is needed for the next claim.
