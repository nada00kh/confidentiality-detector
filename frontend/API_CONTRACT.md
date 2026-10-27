# WASHQ API contract

This is the agreement between the frontend and the FastAPI backend.
The frontend already works with these shapes through `js/mock.js`. When the backend returns the same JSON,
set `USE_MOCK: false` in `js/config.js` and the pages will use the real server with no other changes.

Base URL in development: `http://localhost:8000` (change `API_BASE` in `js/config.js` if needed).

## Privacy rules for the backend

- Never store the original message or any sensitive value in the database or logs.
- Logs keep only: time, data types and counts, decision, reason, masking result, operation ID.
- WASHQ never sends text to an AI model. The employee copies the safe text (with labels such as `[PERSON_NAME]`) and uses it wherever they choose.

## Data type codes

| Code | Label |
|---|---|
| `PERSON_NAME` | Person name |
| `NATIONAL_ID` | National ID |
| `PHONE` | Phone number |
| `EMAIL` | Email address |
| `IBAN` | IBAN |
| `CARD_NUMBER` | Card number |
| `PASSWORD` | Password |
| `CONFIDENTIAL` | Confidential topic (no value, just the topic) |

New types can be added. The frontend shows whatever `label` the backend sends.
For the logs filter, also add the type to `TYPE_OPTIONS` in `js/logs.js`.

## Decisions

There are only two:

- `ALLOW`: no sensitive data was found. The text is safe to share as it is. `safe_text` = the same text.
- `BLOCK`: sensitive data was found, so the original must not be shared. Every detected value is replaced by a
  placeholder such as `[PERSON_NAME]`, and that masked copy is returned in `safe_text` for the employee to copy.
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

Response:

```json
{
  "operation_id": "WSQ-000317",
  "decision": "BLOCK",
  "reason": "Sensitive data found, masked copy returned",
  "detected": [
    { "type": "PERSON_NAME", "label": "Person name", "count": 1 },
    { "type": "NATIONAL_ID", "label": "National ID", "count": 1 }
  ],
  "safe_text": "Summarize the complaint from customer [PERSON_NAME], ID [NATIONAL_ID], about invoice #4471.",
  "spans": [
    { "start": 38, "end": 52, "type": "PERSON_NAME" },
    { "start": 57, "end": 67, "type": "NATIONAL_ID" }
  ]
}
```

- `safe_text`: for `ALLOW`, the original text; for `BLOCK`, the masked copy (or `null` only if masking failed).
- For a clean text the answer is `{"decision": "ALLOW", "reason": "No sensitive data found", "detected": [], "safe_text": "<same text>", "spans": []}`.
- `spans` are character positions of the masked values in the original prompt, without the values themselves.
  The frontend uses them only to animate the values turning into placeholders on the employee's own screen.
  They are optional; send `[]` if not available (the frontend then shows the safe text directly).
- `reason` is a short sentence shown in the logs, for example `"Sensitive data found, masked copy returned"`.

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

## Errors

Any error: an HTTP 4xx/5xx status with `{"detail": "A short sentence the employee can read."}`.
The frontend shows `detail` to the user.

## CORS

If the frontend is opened from a file or another port, enable CORS in FastAPI for development
(`CORSMiddleware` with `allow_origins=["*"]`), or serve the frontend folder from FastAPI with `StaticFiles`.
