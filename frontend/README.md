# WASHQ frontend

The three WASHQ screens, built with plain HTML, CSS and JavaScript. No build step and no packages to install.

| Page | File |
|---|---|
| Welcome (choose Employee or Administrator) | `index.html` |
| Employee Workspace (scan, mask, copy) | `workspace.html` |
| Admin Dashboard | `admin.html` |
| Security Logs | `logs.html` |

## Open it

Double-click `index.html`, or serve the folder (recommended, closer to production):

```
python -m http.server 5500
```

then open http://localhost:5500.

## Demo mode

Right now the pages run on demo data (`js/mock.js`), so they work without the backend.
Clicking a KPI card on the dashboard opens the logs already filtered (for example only BLOCK).
A "DEMO MODE" / "DEMO DATA" badge shows while this is on.

There is no sign-in yet: on the welcome page, Employee opens the workspace and Administrator opens the dashboard.

In the workspace, click a sample on the start screen to put it in the box, then press Send.
ALLOW means the text is clean. BLOCK means sensitive data was found: the original must not be shared, and WASHQ
shows a masked copy you can copy and use instead:

- Masks a name and an ID: `Summarize the complaint from customer Ahmed Alotaibi, ID 1098765432, about invoice #4471.`
- Masks a phone number and an email: `Please call Sara Alharbi on 0551234567 or email sara.alharbi@example.com about the contract renewal.`
- Masks a password and a card number: `The client can't log in. Their password is Riyadh@2024 and card 4111 1111 1111 1111 was declined.`
- Nothing sensitive: `Draft a polite reply to a customer asking about a delayed refund.`

The same text always gives the same result. WASHQ never sends your text to an AI model.

Text you scan in demo mode is added to the demo logs and dashboard (stored only in your browser).

The demo scanning is a few simple patterns, only to show the screens. It is not the real detector.

## Connecting the backend

1. Build the FastAPI endpoints described in `API_CONTRACT.md`.
2. In `js/config.js`, set `USE_MOCK: false` and check `API_BASE`.
3. Reload the pages.

All calls to the backend live in `js/api.js`. The pages never call the server directly.

## Files

```
index.html        welcome page (start here)
workspace.html    employee workspace
admin.html        admin overview
logs.html         security logs
css/washq.css     brand colors, layout and components for all pages
js/config.js      demo mode switch and API address
js/api.js         the single connection point to the backend
js/mock.js        demo backend that runs in the browser
js/welcome.js     welcome page intro and transition
js/brand.js       logo, icon and mascot (the W caracal with changing eyes)
js/workspace.js   scanning animation, result card with sanitized text and copy
js/admin.js       dashboard numbers, chart, data types, latest events
js/logs.js        logs table, filters, expandable rows and pages
API_CONTRACT.md   request and response shapes for the backend team
```
