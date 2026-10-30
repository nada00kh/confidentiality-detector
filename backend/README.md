# WASHQ local demo: backend, setup and limits

WASHQ is the bootcamp demo application around the confidentiality detector: a FastAPI backend (`backend/`) and a static HTML/CSS/JavaScript frontend (`frontend/`). It is a **local prototype**: everything runs on one computer, and text is never sent to an external service.

## What decides, and what was evaluated

| Component | Where | Status |
|---|---|---|
| **Core detector** | the frozen R3 checkpoint (`checkpoints/r2_e3b_positive`) + English rules v3, always in `strict` mode, called through `backend/app/model_detector.py`. The frozen package `src/confidentiality_detector/` is used as is. | **The evaluated system.** All reported results, including Challenge v2, are for this component alone (`reports/FINAL_REPORT.md`). |
| **Saudi demo extension** | `backend/app/saudi_rules.py`: regular expressions for Saudi mobile numbers, national ID (10 digits starting with 1), iqama (10 digits starting with 2) and e-mail, also in Arabic-Indic or Persian digits | **Demo only, never evaluated.** It is not part of Challenge v2 or any reported result. It is not an Arabic NER model, and the application does not claim Arabic language support. |
| **Application layer** | `sanitizer.py` (merging and masking), `storage.py` (audit log), `main.py` (API) | Software, covered by `backend/tests/`; not an ML component |

How one scan is answered (`POST /api/check`):

1. The core detector inspects the text in `strict` mode. If it is unavailable or cannot complete the inspection, the scan fails with HTTP 503 and returns no text.
2. The Saudi rules run on the same text.
3. Overlapping findings become one masked span that covers all of them. **Its type comes from the core finding whenever one is involved.** A Saudi type (National ID, Iqama, …) is used only for a value the core detector did not find. So the extension can add masked values, and turn ALLOW into BLOCK, but it never removes or relabels a core finding.
4. **Secondary hints (demo only).** A hint is added in a separate response field, `pattern_hints`, when two things hold:
   * a Saudi rule matches the **whole** value;
   * the core detector typed that value differently, for example a national ID typed ACCOUNTNUMBER.

   Example: **Account number**, *Also matches a Saudi national ID pattern (demo rule).*
   * A hint is a format match, not proof that the value is a real or verified ID.
   * It never changes the type, the counts, the masked text or the decision.
   * It is not stored in the audit log and not counted on the dashboard.
   * A Saudi match inside a longer value, such as the digits inside a spaced IBAN, gives no hint.
5. Nothing masked: **ALLOW**, and the original text is returned. Something masked: **BLOCK**, and a masked copy with placeholders such as `[PERSON_NAME]` is returned.
6. The audit log records the time, decision, reason, primary types and counts, and an operation ID. It never stores the text, a value or a hint.

Observed with fictional inputs (2026-10-30):
* The core detector already flags most Saudi 10-digit numbers itself, usually as an account number. The app therefore shows **Account number** with a national ID, iqama or Saudi mobile hint.
* **National ID** or **Iqama** appear as the type only for values the core detector misses, for example numbers written in Arabic-Indic digits.

## Setup

1. **Checkpoint.** Put the six files of `r2_e3b_positive` directly in `checkpoints/r2_e3b_positive/` (`docs/INTEGRATION.md` §1.2). Check it: `python scripts/check_frozen_identity.py` must print `Same detector as the frozen record: yes`.
2. **Environment.** Choose one. Always pass `--frozen`, so `uv.lock` is used as is.
   * **Project environment** (simplest):

     ```powershell
     . .\scripts\dev_env.ps1
     uv sync --frozen --inexact --group web    # adds FastAPI, Uvicorn and their dependencies
     ```

     The detector's libraries keep the versions in `uv.lock`; `check_frozen_identity.py` reports any change under `runtime`. `--inexact` keeps packages of other groups (for example the notebooks group) installed.
   * **Separate environment**, which leaves the frozen environment untouched (used for the 2026-10-30 verification):

     ```powershell
     $web = "$env:LOCALAPPDATA\confidentiality-detector\venv-web"
     uv export --frozen --no-hashes --no-emit-project --group web -o "$env:TEMP\washq-web.txt"
     uv venv --python 3.13 $web
     uv pip sync --python "$web\Scripts\python.exe" "$env:TEMP\washq-web.txt"
     uv pip install --python "$web\Scripts\python.exe" --no-deps -e .
     & "$web\Scripts\Activate.ps1"
     ```

   Keep environments outside OneDrive-synced folders (`docs/INTEGRATION.md` §1.3).

## Run

Use two terminals, both at the repository root with the environment active.

**Backend:**

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

* The model loads before the server prints `Application startup complete`, which takes a few seconds.
* Check readiness at http://127.0.0.1:8000/health:
  * `200 {"status": "ready", "model_loaded": true}`: scans can run;
  * `503 {"status": "not_ready", "model_loaded": false}`: the checkpoint could not be loaded. The terminal shows `Detector could not be loaded (...)`, and every scan answers 503.
  * `/health` only reads the in-memory state; it never loads or runs the model.

**Frontend:**

```powershell
python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

* Open http://localhost:5500 (or http://127.0.0.1:5500).
* The backend accepts browser calls only from these two addresses. A page opened as a file, or from another port, shows "WASHQ couldn't scan this text".

**Settings.** These environment variables are all optional:

| Variable | Default | Notes |
|---|---|---|
| `WASHQ_MODEL_DIR` | `checkpoints/r2_e3b_positive` | the frozen checkpoint |
| `WASHQ_POLICY_PATH` | `configs/inference/policy.json` | the frozen policy |
| `WASHQ_DEVICE` | `cpu` | the evaluated configuration |
| `WASHQ_DB_PATH` | `backend/data/washq.sqlite3` | audit log (git-ignored); delete it to empty the dashboard |
| `WASHQ_TIMEZONE` | `Asia/Riyadh` | groups the dashboard's daily numbers |
| `WASHQ_CORS_ORIGINS` | `http://localhost:5500,http://127.0.0.1:5500` | comma-separated |

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/check` | Body `{"text": "..."}` with 1–10,000 characters. Returns `operation_id`, `decision`, `reason`, `detected` (primary types and counts), `safe_text`, `spans` (positions in JavaScript string units) and `pattern_hints` (secondary demo-rule hints, often empty). |
| `GET /api/stats?days=7` | Dashboard numbers (primary types only) |
| `GET /api/logs?decision=&type=&days=&q=&page=&page_size=` | Audit log, newest first (primary types only) |
| `GET /health` | Readiness: 200 `ready` when the detector is loaded, 503 `not_ready` when it is not |

* **Errors** are returned as `{"detail": "<fixed sentence>"}`:
  * **422**: an invalid request; the input is never echoed.
  * **503**: the detector is unavailable or failed, or the audit log could not be written.
* **Full shapes:** `frontend/API_CONTRACT.md`. Interactive documentation is served at http://127.0.0.1:8000/docs.

## What masking can and cannot guarantee

* **It can guarantee:**
  * Every character that either detector flagged is replaced. Overlapping findings are merged, and a finding that cuts a word covers the whole word.
  * Values are never stored or logged.
  * A failure never produces ALLOW or a partly masked copy: it gives a 503, or BLOCK without a copy.
* **It cannot guarantee:**
  * **Values the detectors miss stay in the masked copy.** Challenge v2 measured the core detector's decisions and spans, not the masked copy: 2 of 200 sensitive cases were allowed, and 24 of 236 entities were not found with exact boundaries. Masking completeness itself was never evaluated. The workspace therefore asks the user to "Review the masked text before sharing. Automatic masking may miss sensitive information."
  * **That a blocked text really contained sensitive data.** About one harmless text in three was blocked on Challenge v2 (70/200), typically tracking, order and version numbers.

## Known limits of the local demo

* **Not production software.**
  * There is no sign-in; the avatar in the workspace is decoration.
  * `/api/logs` and `/api/stats` have no access control. Keep the server bound to `127.0.0.1`.
* **Text limit.** At most 10,000 characters per scan. Longer text is refused (422), and the workspace shows "couldn't scan".
* **Language.** The core detector was trained and evaluated on English text only.
  * On Arabic text, Saudi values are found mainly by the unevaluated Saudi rules.
  * The model's predictions on Arabic text are not evidence of Arabic support. For example, it can take Arabic words for names.
* **Saudi values are usually labelled "Account number"**, the core label, with a demo-rule hint (see above). Hints are format matches only. The Saudi rules cover four formats; they are not Arabic PII detection.
* **Scan time limit in the browser: 60 seconds** (`CHECK_TIMEOUT_MS` in `frontend/js/config.js`). The slowest scan measured at 10,000 characters on a laptop CPU took about 11 seconds.
  * A slower scan is stopped and shown as "couldn't scan", never as a result.
  * The server may still finish it and record it in the audit log.
* **Fonts.** The pages load fonts from Google Fonts. No text is sent, but the visitor's IP address is.
* **Speed.** Scans run one at a time on the CPU. Long texts can take seconds.

## Tests

```powershell
python -m pytest backend/tests -q                  # needs the web group; tests marked real_model skip without the checkpoint
python -m pytest -q                                # the detector's own tests (tests/)
node --test frontend/tests/api_client.test.mjs     # the frontend API client: timeout, errors, answer check (Node 18+)
```

| File | Covers |
|---|---|
| `test_check.py` | the API contract, validation, error responses, privacy |
| `test_logs_stats.py` | the audit log, dashboard and logs endpoints |
| `test_model_detector.py` | the frozen-detector adapter, fail-closed behaviour, start-up, combined detector |
| `test_sanitizer.py` | merging, typing and masking of findings |
| `test_saudi_rules.py` | the Saudi rules on their own, including their known gaps |
| `test_saudi_extension.py` | Saudi findings are supplemental, and secondary hints change nothing else. Covers the German IBAN regression, Saudi mobile/ID/iqama, ordinary account numbers and overlaps with English categories. With the checkpoint, the core results equal direct `strict` inference |
| `test_real_model.py` | the real checkpoint through the API |
