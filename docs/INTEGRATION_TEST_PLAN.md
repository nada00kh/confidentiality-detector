# Manual integration and demo test plan (template)

**Status: template; the manual UI pass has not been executed.**
* The "Actual" and "Pass/fail" columns are for that manual pass, and are empty on purpose.
* The inputs of T01–T24 and §3.4 were also run automatically through the real server on 2026-10-30. That run checked integration consistency (§2) only, not the policy column.
* Part of it is repeatable with `python -m pytest backend/tests` (`backend/README.md`).

**What this is:** acceptance testing of the frontend + FastAPI integration around the frozen detector, plus a rehearsal list for the live demo.

**What this is not:** an ML evaluation. These ~30 inputs are written by the team, so they say nothing independent about detection quality. The independent result is `challenge_v2` (`reports/FINAL_REPORT.md` §5). Do not report these results as model performance.

## 1. Rules for the inputs

* **Synthetic values only:**
  * phone numbers in the reserved 555-01xx range;
  * invented names, except deliberate public figures;
  * e-mail domains `example.com` / `example.org`;
  * IPv4 documentation addresses (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`, RFC 5737);
  * public test card numbers and the published specimen IBAN.
* **Never use** real personal data, real credentials, `challenge_v2` cases (developers have never seen them), or `dev_v1` / `challenge_v1` texts.
* **The inputs below are drafts.** The team reviews and finalises them, then fills in the "Expected result" column **before** any execution (§4), and does not change it afterwards.
* **Mode:** always `strict`, passed explicitly by the backend. Never a user option (`docs/INTEGRATION.md` §2.2).
* **Types in the app:** the app shows type codes instead of detector labels (`backend/app/labels.py`). For example, FIRSTNAME and LASTNAME become PERSON_NAME, PHONENUMBER becomes PHONE, STREET becomes STREET_ADDRESS, and IPV4 becomes IP_ADDRESS.
* **Saudi demo extension:** it can add findings to the evaluated detector's (§3.4). It is not part of the evaluated system.

## 2. How each test passes

A test can fail in three independent ways. Record each one.

| Check | Pass when | Source |
|---|---|---|
| **Consistency (integration)** | The app's decision and the categories it shows match the direct call `detector.inspect(text, "strict")` (or the CLI: `python -m confidentiality_detector --model-dir checkpoints/r2_e3b_positive --mode strict --file <input>`), translated into type codes. Where a Saudi rule also matched (§3.4), the app may show **additional** masked values, but never fewer and never a different type for a value the detector found | `docs/INTEGRATION.md` §7 |
| **Fail-closed and privacy (integration)** | An error never shows a result: the UI says "WASHQ couldn't scan this text", and there is nothing to copy. No detected value appears in the masked copy, the logs or the audit database | `docs/INTEGRATION.md` §3–4 |
| **Policy match (detector behaviour, informational)** | the decision equals the expected decision under `docs/POLICY.md` | `docs/POLICY.md` |

A policy mismatch on a look-alike or an out-of-scope secret is a **known detector limitation** (false BLOCK). It is not an integration defect, and it must not be "fixed" in the API or frontend. Record it in Notes.

## 3. Test cases

Legend:
* **Expected** = the decision and categories under the written policy, fixed before execution (draft below, to be confirmed by the team).
* **Known risk** = what the aggregate `challenge_v2` results suggest *may* happen for this kind of input. It is not a prediction for this input.

### 3.1 Detection behaviour through the API and UI

| ID | Scenario | Synthetic input (draft) | Expected (policy) | Actual: API/UI · direct CLI | Pass/fail (consistency · policy) | Notes |
|---|---|---|---|---|---|---|
| T01 | Clean prompt | `Please summarise the attached meeting notes for the team.` | ALLOW, `NO_SENSITIVE_ENTITIES` | | | Also the documented smoke example (`docs/INTEGRATION.md` §1.5) |
| T02 | Clean prompt, writing request | `Rewrite this paragraph so it sounds more formal: we are moving the launch to next quarter.` | ALLOW | | | |
| T03 | Clean prompt, code question | `Why does this Python loop never stop? while i < 10: print(i)` | ALLOW | | | |
| T04 | One protected value: e-mail | `Forward the draft to lena.morrow@example.com before Friday.` | BLOCK: EMAIL | | | |
| T05 | One protected value: phone | `Call the supplier back on 555-0147 after lunch.` | BLOCK: PHONENUMBER | | | |
| T06 | Person name (private individual) | `Can you thank Mira Okafor for the quick turnaround?` | BLOCK: FIRSTNAME, LASTNAME | | | |
| T07 | Person name (public figure) | `Summarise Marie Curie's main discoveries in three bullet points.` | BLOCK: FIRSTNAME, LASTNAME | | | Intended by policy (`docs/POLICY.md` §3): a correct BLOCK, though users may see it as friction. Explain this in the demo if shown |
| T08 | Credentials | `Log in as jdoe with password Zq81kLm!x and restart the job.` | BLOCK: USERNAME, PASSWORD | | | |
| T09 | Card number with CVV and context | `Charge card 4111 1111 1111 1111, CVV 123, for the renewal.` | BLOCK: CREDITCARDNUMBER, CREDITCARDCVV | | | Public test card number |
| T10 | IBAN (published specimen) | `Please wire the deposit to DE89 3704 0044 0532 0130 00.` | BLOCK: IBAN | | | The README example. Before 2026-10-30 the app labelled it PHONE, because the Saudi phone rule matches inside it; that is fixed, with regression tests in `backend/tests/test_saudi_extension.py` |
| T11 | Account number with cue | `My account number is 40018822 at the credit union.` | BLOCK: ACCOUNTNUMBER | | | |
| T12 | SSN | `The new hire's SSN is 123-45-6789, please update the HR form.` | BLOCK: SSN | | | Common placeholder value |
| T13 | Street | `Ship the samples to 42 Clover Lane by Tuesday.` | BLOCK: STREET | | | STREET excludes the house number (annotation convention) |
| T14 | IPv4 host address | `The server at 192.0.2.17 stopped answering pings.` | BLOCK: IPV4 | | | RFC 5737 address |
| T15 | Multiple categories | `Hi, please log in as jdoe with password Zq81kLm!x and call Mira Okafor on 555-0142.` | BLOCK: FIRSTNAME, LASTNAME, PASSWORD, PHONENUMBER, USERNAME | | | Documented smoke example (§1.5) |
| T16 | Multiple categories in structured text | `{"name": "tomas reyes", "email": "t.reyes@example.org", "ip": "198.51.100.23"}` | BLOCK: FIRSTNAME, LASTNAME, EMAIL, IPV4 | | | Lowercase names: a known weak spot |
| T17 | Look-alike: tracking number | `Where is parcel 1Z999AA10123456784? It has not moved since Monday.` | ALLOW | | | Known risk: in `challenge_v2`, all 5 ALLOW cases with tracking numbers were blocked (as ACCOUNTNUMBER/IBAN) |
| T18 | Look-alike: four-part version | `After upgrading to firmware 2.4.1.7 the dashboard is slow.` | ALLOW | | | Known risk: 5 of 5 version cases blocked (as IPV4) |
| T19 | Look-alike: order / invoice number | `Order 7730-118-2245 was invoiced twice, please check.` | ALLOW | | | Known risk: order and invoice numbers taken for SSN |
| T20 | Look-alikes that rarely misfire | `Error code E-4012 appeared on 2026-03-14 during the nightly build.` | ALLOW | | | Dates and error codes caused no false positive in `challenge_v2`; a good ALLOW demo case |
| T21 | Short number in ordinary context (CVV policy) | `Book room 482 for the workshop with 12 chairs.` | ALLOW | | | A 3–4 digit number is a CVV only with card evidence (`docs/POLICY.md` §4) |
| T22 | Out-of-scope secret (API key) | `Our config has api_key = demo-key-9fJ2kL0qWx81mNbV7cRt; why does the call fail?` | ALLOW (API keys are out of scope; decision F) | | | Known risk: API keys predicted as PASSWORD (4 of 5 such cases blocked). A BLOCK is safe for confidentiality but counts as a false BLOCK |
| T23 | Long harmless document | about 3,500 characters of invented meeting notes with dates, versions and ticket numbers but no protected value | ALLOW | | | Several windows; look-alikes accumulate over long text (`test_long` False BLOCK 5/28) |
| T24 | Long document, one value far from the start | the same notes with one e-mail `j.alvarez@example.com` near the end | BLOCK: EMAIL | | | Checks the finding past the first window. The position must be correct in the UI |

### 3.2 Input validation, API errors and fail-closed behaviour

| ID | Scenario | How to run | Expected | Actual: API · UI | Pass/fail | Notes |
|---|---|---|---|---|---|---|
| T25 | Empty or whitespace-only text | submit `""` and `"   "` in the UI, then send them to the API | UI: not submitted ("Paste some text first."). API: 422 with a fixed message | | | The app never reaches the detector's own `EMPTY_INPUT` ALLOW |
| T26 | Text over 10,000 characters | submit 10,001 characters of harmless text | API: 422, a fixed message that echoes nothing. UI: "WASHQ couldn't scan this text", no result | | | The API limit is 10,000 characters, so the detector's 100,000-character `INPUT_TOO_LARGE` is not reached |
| T27 | Invalid request body | send JSON without the text field, with a number or `null` as text, and with an extra field such as `"mode"` | 422; nothing is inspected; the response does not echo the input | | | `backend/tests/test_check.py` covers this automatically |
| T28 | Backend unavailable or hanging | stop the API and submit T01. To test the time limit, set `CHECK_TIMEOUT_MS` to 2000 in `js/config.js` and submit about 10,000 characters of Arabic text (the slowest kind, 6–11 s); restore 60000 afterwards | UI: "WASHQ couldn't scan this text. Couldn't reach the WASHQ server …" or "… No answer within 2 seconds …". The spinner stops; no result; nothing to copy; the text stays in the box | | | `frontend/tests/api_client.test.mjs` covers the timeout and a late answer automatically |
| T29 | Detector cannot load at start-up | start the API with `WASHQ_MODEL_DIR` set to a wrong folder | the server starts and logs "Detector could not be loaded". `/health` answers 503 `{"status": "not_ready", "model_loaded": false}`; every scan answers 503 "Detection is not available right now …"; never ALLOW | | | With the checkpoint in place, `/health` answers 200 `ready` |
| T30 | Exception during inspection | in a test only, make the detector raise | 503 "Detection failed …"; nothing recorded; the log holds only the exception type | | | `backend/tests/test_model_detector.py` and `test_real_model.py` cover this; do not modify the frozen detector files (`docs/INTEGRATION.md` §8) |

### 3.3 Frontend display and privacy

| ID | Scenario | How to check | Expected | Actual | Pass/fail | Notes |
|---|---|---|---|---|---|---|
| T31 | BLOCK display | run T15 | BLOCK card shows: the types and counts; the masked copy with placeholders; the note "Review the masked text before sharing. Automatic masking may miss sensitive information."; and Copy. No detected value remains on screen after the masking animation | | | The animation shows the user's own text in their browser before masking it; nothing leaves the page |
| T32 | ALLOW display | run T01 | ALLOW card "Nothing sensitive", the text unchanged, and Copy | | | |
| T33 | No values anywhere | after T08 and T15, inspect the server console, the audit database and the logs page | the response holds the masked copy (BLOCK) or the user's own text (ALLOW), never a detected value; logs and database hold decision, reason, types and counts only | | | `docs/INTEGRATION.md` §4 |
| T34 | Fail-closed message wording | after T26, T28 and T29 | the message states the real reason (invalid request / server unreachable / detection not available) and does not claim sensitive data was found | | | |

### 3.4 Saudi demo extension (demo only, not evaluated)

**Expected app result** is the app's documented behaviour (`backend/README.md`), observed with the frozen checkpoint on 2026-10-30. These rows check the integration. They say nothing about the quality of the Saudi rules, which were never evaluated.

| ID | Scenario | Synthetic input | Expected app result | Actual | Pass/fail | Notes |
|---|---|---|---|---|---|---|
| T35 | Saudi mobile that the core detector finds | `Please call Khalid on 0551234567 tomorrow morning.` | BLOCK: Person name, Account number; hint under Account number: "Also matches a Saudi mobile number pattern (demo rule)." | | | Core types are kept; the Saudi rule matches the same value |
| T36 | Saudi mobile in Arabic-Indic digits | `رقم الهاتف: ٠٥٥١٢٣٤٥٦٧` | BLOCK: Phone number; no hint | | | The core detector alone answers ALLOW; the Saudi rule adds the BLOCK |
| T37 | National ID | `The visitor's national ID is 1098765432.` | BLOCK: Account number; hint "Also matches a Saudi national ID pattern (demo rule)." | | | "National ID" as the type appears only for values the core detector misses |
| T38 | Iqama | `Iqama number 2123456789 expires next month.` | BLOCK: Account number; hint "Also matches an Iqama-like pattern (demo rule)." | | | |
| T39 | IBAN containing a Saudi-looking number | T10 | BLOCK: IBAN only; no hint | | | The former mislabelling (§3.1, T10); a Saudi match inside a longer value gives no hint |
| T40 | Harmless 10-digit number | `Ticket 1000234567 was escalated to tier 2.` | BLOCK: Account number (policy: ALLOW) | | | A known false BLOCK by the core detector; present it honestly |

## 4. Recording procedure

1. Finalise the inputs and the "Expected" column; both team members agree. Commit or date-stamp the finalised table **before** the first run.
2. Run each input through the direct CLI and through the API/UI on the same computer. Paste only the decision, reason and categories into "Actual"; never paste values.
3. Mark the two pass/fail checks separately: consistency, then policy.
4. Repeat T01, T15, T17 and T24 on the second computer (cross-computer consistency, `docs/INTEGRATION.md` §1.6, §7).
5. For the live demo, choose cases whose behaviour has been recorded here. Present any false BLOCK honestly, as the documented limitation.

| Run | Date | Computer | Commit of integration branch | Executed by | Result summary |
|---|---|---|---|---|---|
| | | | | | |
