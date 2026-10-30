# WASHQ API contract

This is the agreement between the frontend and the FastAPI backend.
The backend in `backend/` implements it (setup and run: `backend/README.md`). The optional demo mode
(`USE_MOCK: true` in `js/config.js`) returns the same shapes from `js/mock.js`.

Base URL in development: `http://localhost:8000` (change `API_BASE` in `js/config.js` if needed).

## Privacy rules for the backend

- Never store the original message or any sensitive value in the database or logs.
- Logs keep only: time, data types and counts, decision, reason, masking result, operation ID.
- WASHQ never sends text to an external AI service: the detector runs locally. The employee copies the masked text
  (with labels such as `[PERSON_NAME]`), reviews it, and uses it wherever they choose.

## Data type codes

| Code | Label | Produced by |
|---|---|---|
| `PERSON_NAME` | Person name | core detector (FIRSTNAME, LASTNAME) |
| `NATIONAL_ID` | National ID | Saudi demo extension only |
| `IQAMA` | Iqama number | Saudi demo extension only |
| `PHONE` | Phone number | core detector (PHONENUMBER), Saudi demo extension |
| `EMAIL` | Email address | core detector, Saudi demo extension |
| `IBAN` | IBAN | core detector |
| `CARD_NUMBER` | Card number | core detector (CREDITCARDNUMBER) |
| `CARD_CVV` | Card security code | core detector (CREDITCARDCVV) |
| `ACCOUNT_NUMBER` | Account number | core detector (ACCOUNTNUMBER) |
| `SSN` | Social Security number | core detector |
| `USERNAME` | Username | core detector |
| `PASSWORD` | Password | core detector |
| `STREET_ADDRESS` | Street address | core detector (STREET) |
| `IP_ADDRESS` | IP address | core detector (IPV4) |
| `CONFIDENTIAL` | Confidential topic (no value, just the topic) | reserved; no detector produces it |

Where findings of the core detector and the Saudi demo extension overlap, the core detector's type is used
(`backend/README.md`). The frontend shows whatever `label` the backend sends. A new type also needs an entry in
`backend/app/labels.py` and in `TYPE_OPTIONS` in `js/logs.js` (the logs filter).

## Decisions

There are only two:

- `ALLOW`: no sensitive data was found. `safe_text` = the same text.
- `BLOCK`: sensitive data was found, so the original must not be shared. Every detected value is replaced by a
  placeholder such as `[PERSON_NAME]`, and that masked copy is returned in `safe_text` for the employee to copy.
  Automatic masking may miss values the detector did not find, so the frontend asks the employee to review the
  masked text before sharing it.
  If the backend ever can't produce a masked copy, it returns `BLOCK` with `safe_text: null`; the frontend then
  shows the reason and no copy button.

In short: ALLOW = clean, BLOCK = sensitive data found (masked copy provided).

---

## 1. Check a message

`POST /api/check`

Request:

```json
{ "text": "Summarize the complaint from customer Ahmed Alotaibi, ID 1098765432, about invoice #4471." }
```

`text` must have 1–10,000 characters and not be blank; no other fields are accepted.

Response (the real backend with the frozen checkpoint, 2026-10-30):

```json
{
  "operation_id": "WSQ-000317",
  "decision": "BLOCK",
  "reason": "Sensitive data found, masked copy returned",
  "detected": [
    { "type": "PERSON_NAME", "label": "Person name", "count": 2 },
    { "type": "ACCOUNT_NUMBER", "label": "Account number", "count": 1 }
  ],
  "safe_text": "Summarize the complaint from customer [PERSON_NAME] [PERSON_NAME], ID [ACCOUNT_NUMBER], about invoice #4471.",
  "spans": [
    { "start": 38, "end": 43, "type": "PERSON_NAME" },
    { "start": 44, "end": 52, "type": "PERSON_NAME" },
    { "start": 57, "end": 67, "type": "ACCOUNT_NUMBER" }
  ],
  "pattern_hints": [
    { "type": "ACCOUNT_NUMBER", "label": "Account number", "pattern": "SAUDI_NATIONAL_ID",
      "note": "Also matches a Saudi national ID pattern (demo rule).", "count": 1 }
  ]
}
```

- `safe_text`: for `ALLOW`, the original text; for `BLOCK`, the masked copy (or `null` only if masking failed).
- For a clean text the answer is `{"decision": "ALLOW", "reason": "No sensitive data found", "detected": [], "safe_text": "<same text>", "spans": []}`.
- `spans` are character positions of the masked values in the original prompt, in JavaScript string units (UTF-16), without the values themselves.
  The frontend uses them only to animate the values turning into placeholders on the employee's own screen.
  They are optional; send `[]` if not available (the frontend then shows the safe text directly).
- `reason` is a short sentence shown in the logs, for example `"Sensitive data found, masked copy returned"`.
- `pattern_hints`: secondary, demo-only explanations. This is usually an empty list.
  - **When an entry appears:** a Saudi demo rule matches a whole value that the core detector typed differently.
  - **What an entry holds:** the primary `type` and `label` (unchanged, also in `detected`), the `pattern` matched (`SAUDI_NATIONAL_ID`, `SAUDI_IQAMA` or `SAUDI_MOBILE`), the `note` to show, and the number of masked values it applies to.
  - **What a hint is not:** a format match, not proof of a real ID. It never changes `decision`, `detected`, `spans` or `safe_text`, and it is not stored in the logs or counted in the statistics.
  - **Contents:** no values and no positions.

## 2. Send to the AI model (removed)

The frontend no longer calls `POST /api/chat`. WASHQ does not send text to any AI model.

## 3. Dashboard numbers

`GET /api/stats?days=7`

Response:

```json
{
  "days": 7,
  "total": 1284,
  "allowed": 410,
  "blocked": 874,
  "daily": [
    { "date": "2026-10-15", "allow": 61, "block": 116 }
  ],
  "top_types": [
    { "type": "PERSON_NAME", "label": "Person name", "count": 412 }
  ],
  "latest": [ /* up to 6 log items, same shape as /api/logs items */ ]
}
```

- `allowed` = clean texts, `blocked` = texts with sensitive data. `allowed` + `blocked` = `total`, and the `daily` values add up to the same totals.
- `daily` has one entry per day, oldest first, `date` in the company's local time zone.

## 4. Security logs

`GET /api/logs?decision=BLOCK&type=PASSWORD&days=7&q=WSQ-0003&page=1&page_size=10`

All parameters are optional. `decision` is `ALLOW` or `BLOCK`; `type` is a data type code; `q` searches the operation ID.

Response:

```json
{
  "total": 312,
  "page": 1,
  "page_size": 10,
  "items": [
    {
      "operation_id": "WSQ-000318",
      "time": "2026-10-21T07:42:00Z",
      "detected": [ { "type": "CARD_NUMBER", "label": "Card number", "count": 1 } ],
      "decision": "BLOCK",
      "reason": "Sensitive data found, masked copy returned",
      "masking": "1 item masked"
    }
  ]
}
```

Newest first. `masking` is a short text such as `2 items masked` (BLOCK) or `No changes` (ALLOW).

## 5. Readiness

`GET /health`

- `200 {"status": "ready", "model_loaded": true}`: the detector is loaded, so scans can run.
- `503 {"status": "not_ready", "model_loaded": false}`: the detector could not be loaded, so every scan answers 503.

It reads the server's in-memory state only. It never loads or runs the model, and it reveals no paths or error details. The pages do not call it; it is for the people running the demo.

## Errors

Any error: an HTTP 4xx/5xx status with `{"detail": "A short sentence the employee can read."}`.
The frontend shows `detail` to the user, and never shows a result for a failed scan.
The frontend stops waiting for `POST /api/check` after `CHECK_TIMEOUT_MS` (60 seconds, `js/config.js`). It then shows the scan as failed and ignores any later answer.

- `422`: the request is not valid (empty or blank text, more than 10,000 characters, wrong or extra fields). The
  message is built from field names only and never repeats the input.
- `503`: the detector is not available or failed, or the scan could not be recorded. No text is returned.

## CORS

The backend accepts browser calls only from `http://localhost:5500` and `http://127.0.0.1:5500` (change with
`WASHQ_CORS_ORIGINS`). Serve the frontend from one of these (`backend/README.md`); a page opened as a file is refused.
