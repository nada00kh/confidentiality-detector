# WASHQ frontend

The WASHQ screens, built with plain HTML, CSS and JavaScript. No build step and no packages to install.

| Page | File |
|---|---|
| Welcome (choose Employee or Administrator) | `index.html` |
| Employee Workspace (scan, mask, review, copy) | `workspace.html` |
| Admin Dashboard | `admin.html` |
| Security Logs | `logs.html` |

## Open it

The pages call the local WASHQ backend at `http://localhost:8000` (`js/config.js`). Start the backend first, as described in `backend/README.md`, then serve this folder from the repository root:

```
python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Open http://localhost:5500.
* Opening `index.html` as a file does not work with the backend: the browser's request is refused, and the workspace shows "WASHQ couldn't scan this text".
* There is no sign-in: on the welcome page, Employee opens the workspace and Administrator opens the dashboard.

## The workspace

Click a sample on the start screen to put it in the box, then press Send.

* **ALLOW:** nothing sensitive was found, and the text can be copied as it is.
* **BLOCK:** sensitive data was found, and the original must not be shared.
  * WASHQ shows a masked copy, with values replaced by placeholders such as `[PERSON_NAME]`, and the types found.
  * It asks the user to **review the masked text before sharing**, because automatic masking may miss sensitive information.
  * When a Saudi demo rule also matches a value of the evaluated core detector, a secondary line appears under the types, for example: **Account number**, *Also matches a Saudi national ID pattern (demo rule).*
    * The type shown is still the core detector's type.
    * The hint is a format match, not proof of a real ID (`backend/README.md`).
* **Any error** shows "WASHQ couldn't scan this text": no network connection, a non-OK answer, an incomplete answer, or **no answer within 60 seconds**.
  * Nothing is shown as safe, and there is nothing to copy.
  * The text stays in the box for another try.
  * An answer that arrives after the time limit is ignored.
  * The limit is `CHECK_TIMEOUT_MS` in `js/config.js`. It applies to scans only; the dashboard and logs pages are unchanged.

The samples, with the results of the frozen checkpoint (CPU, 2026-10-30):

- Name + ID: `Summarize the complaint from customer Ahmed Alotaibi, ID 1098765432, about invoice #4471.`
  * BLOCK: two person names and one **account number**.
  * The hint *Also matches a Saudi national ID pattern (demo rule).* appears: the ID also matches the Saudi rule, and the core detector's type is kept.
- Phone + email: `Please call Sara Alharbi on 0551234567 or email sara.alharbi@example.com about the contract renewal.`
  * BLOCK: two person names, the phone number (typed **account number** by the core detector) and one e-mail.
  * The phone number also gets a Saudi mobile hint.
- Password + card: `The client can't log in. Their password is Riyadh@2024 and card 4111 1111 1111 1111 was declined.`
  * BLOCK: a password and a card number.
- Nothing sensitive: `Draft a polite reply to a customer asking about a delayed refund.`
  * ALLOW.

The text is checked only by the local backend; it is never sent to an external AI service.

## Demo mode (optional)

Setting `USE_MOCK: true` in `js/config.js` runs the pages on `js/mock.js` instead of the backend. A "DEMO MODE" badge shows while it is on.
* Demo mode uses a few simple browser patterns, only to show the screens. It is **not the real detector**.
* Scanned texts go into demo logs stored in the browser.

## Files

```
index.html        welcome page (start here)
workspace.html    employee workspace
admin.html        admin overview
logs.html         security logs
css/washq.css     brand colors, layout and components for all pages
js/config.js      backend address, scan time limit (CHECK_TIMEOUT_MS) and the optional demo-mode switch
js/api.js         the single connection point to the backend
js/mock.js        optional demo backend that runs in the browser
js/welcome.js     welcome page intro and transition
js/brand.js       logo, icon and mascot (the W caracal with changing eyes)
js/workspace.js   scanning animation, result card with masked text, demo-rule hints, review note and copy
js/admin.js       dashboard numbers, chart, data types, latest events
js/logs.js        logs table, filters (every type code the backend records), expandable rows and pages
API_CONTRACT.md   request and response shapes shared with the backend
tests/            automated checks of js/api.js and the answer check: node --test frontend/tests/api_client.test.mjs
```
