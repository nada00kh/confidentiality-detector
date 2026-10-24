# Annotation guidelines (annotation policy v3)

These rules apply to every annotated text in the project:
* the generated training data (`synth.py`);
* the converted ai4privacy data (`labels.LabelPolicy`);
* the hand-written sets (`dev_v1`, `challenge_v1`, and the independent `challenge_v2`).

Product-level policy is in `docs/POLICY.md`.

## General span rules

* **Character spans on the original text.** An annotation is `(start, end, label)` over the exact characters of the document. Tokenisation, subwords and windows are derived from it and never annotated by hand.
* **Exact boundaries.** A span covers the value only. Exclude surrounding quotes, brackets and trailing punctuation (`.` `,` `;` `)`), except where that character belongs to the value: a password ending in `!` keeps the `!`. Keep internal separators: spaces and dashes in card numbers, IBANs, phone numbers and account numbers.
* **No overlapping target spans.**
  * When one value contains another, annotate the outer category only. A name inside an e-mail address is part of the EMAIL; a username inside a URL credential is USERNAME, and the password after the colon is PASSWORD.
  * A path segment such as `/home/<user>/` is a USERNAME.
* **One span per name token.** "Mary Hartigan" is FIRSTNAME `Mary` + LASTNAME `Hartigan`. Titles (Mr., Dr.) are excluded.
* **Partial or masked values.**
  * A partial card such as "ending 1881", or `**** 1234`, is not CREDITCARDNUMBER. Mark it `!PARTIALCARD` if useful.
  * A complete value cut by the end of the text is annotated over what is present.
* **Placeholders are not values:** `<password>`, `{{email}}`, `********`, `your-password-here`, `XXXXX-XXXXX`.
* **Values may span lines or window boundaries.** That is irrelevant to annotation: inference stitches windows back together before decoding.

## Three annotation roles

| Markup in case files | Role | Training | Scoring |
|---|---|---|---|
| `[[LABEL:value]]` | target | B-/I-LABEL | gold entity; document is BLOCK |
| `[[!TYPE:value]]` | out-of-scope look-alike (hard negative) | `O` | any prediction on it is a false positive (reported by TYPE) |
| `[[~TYPE:value]]` | ambiguous | ignored (-100) | predictions on it are neither rewarded nor penalised |

If a document contains a target span, its decision is BLOCK. If it has no target span, its decision is ALLOW, unless it is marked AMBIGUOUS: explicitly, or implicitly when its only annotations are ambiguous spans.

## Per-label rules

| Label | Annotate | Do not annotate (negative or ambiguous) |
|---|---|---|
| **FIRSTNAME / LASTNAME** | identifiable person names in any case (`priya`, `PRIYA`), including public figures (`docs/POLICY.md` §3), in prose, greetings, signatures, e-mail headers, SQL/CSV/JSON fields | company/product/place names (`!COMPANY`, `!PRODUCT`); ordinary words (May, Will, Grace); fictional characters (`~AMBIG`); middle names (ignored); mononyms (`~AMBIG` at entity level, but the document is BLOCK) |
| **USERNAME** | login names and handles: after `username`/`login`/`user=`/`User Id=`; `ssh u@host`; `/home/u/`; `CREATE USER u`; `psql -U u`; `logged in as u`; `@u` mentions; service accounts (`svc_ingest`) | the local part of an e-mail (part of EMAIL); generic system accounts like `root`, `admin` (`~AMBIG`); display names that are person names (FIRST/LAST) |
| **PASSWORD** | the secret value of an account password or passphrase, in prose, JSON/YAML/SQL/env/CLI, connection strings, `.netrc`, alphanumeric passcodes | the word "password"; placeholders; API keys/tokens (out of scope: annotate as look-alikes `!APIKEY` / `!TOKEN`, never `~`, so that a PASSWORD prediction on them counts as a false positive; decision F); numeric door, locker or meeting codes (PIN, `!PIN`) |
| **EMAIL** | full address including `+tag` and sub-domains | — |
| **PHONENUMBER** | the full number with country code, parentheses and separators | extensions written as words ("ext. 4417" outside the span); toll-free numbers when reused as product codes |
| **SSN** | US social security numbers, dashed or (with a cue) undashed | EIN, DUNS, vendor numbers (`!COMPANYID`) |
| **CREDITCARDNUMBER** | full card number (13–19 digits) with its separators | partial or masked numbers; IMEIs; 13-digit barcodes (`!SKU`) |
| **CREDITCARDCVV** | 3–4 digits **with evidence**: a strong cue (CVV/CVC/CCV/CSC/CVN, "card verification …", "on the back of the card") within 60 characters before or 40 after; or a card number or expiry within 120 characters; or "security code" together with a card word | isolated short numbers; one-time codes; PINs; "security code" without card context (`~AMBIG` if unsure) |
| **IBAN** | the IBAN, grouped or compact | BIC/SWIFT (`!BIC`); sort and routing codes (`!ROUTING`) |
| **ACCOUNTNUMBER** | bank or financial account numbers, with their separators | order, invoice, ticket, customer-reference and vendor numbers |
| **STREET** | street name **with** its suffix ("Elm Street", "clover lane"); the house number is **excluded** (training-data convention) | city, state, ZIP; unit/flat numbers |
| **IPV4** | any host IPv4 address, including private ranges | version numbers in version context (`!VERSION`); CIDR ranges, loopback, netmasks (`~AMBIG`) |

## Quality checks that enforce these rules

| Check | Where |
|---|---|
| span inside text, no overlapping targets, value equals the text slice | `Document.validate`, `document_from_ai4privacy` |
| label inside the 13-label scope | `challenge.parse_case`, `synth.validate_synthetic`, `train.load_extra_train`, `PolicyConfig` |
| CVV evidence | `labels.cvv_has_evidence`: used for gold labels (policy v3), generated data (hard error), and case files (warning) |
| explicit document decision consistent with the spans | `challenge.parse_case` |
| no unannotated person name in generated text | `synth.validate_synthetic` |
| card numbers Luhn-valid, IBANs checksum-valid in hand-written sets | `dev_v1` build check; `scripts/challenge_v2.py validate` (warning) |
