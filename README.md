# WASHQ: Confidentiality Detector

WASHQ checks a prompt **before** an employee sends it to an external AI assistant (LLM). It runs entirely on the local computer, looks for 13 categories of sensitive information, and answers:

* **ALLOW**: nothing sensitive was found.
* **BLOCK**: sensitive data was found. WASHQ returns a masked copy in which each detected value is replaced by a placeholder such as `[IBAN]`.

> **Research prototype, not production software.** WASHQ can miss sensitive values, and it blocks many harmless texts (about one in three on the independent benchmark). A masked copy must be reviewed before it is shared. See [What was evaluated](#what-was-evaluated).

## What WASHQ does

```
                    ┌─► core detector (evaluated): R3 model + English rules v3, strict mode ─┐
employee prompt ────┤                                                                        ├─► merge + mask ─► ALLOW / BLOCK + masked copy
                    └─► Saudi demo rules (supplemental, never evaluated) ────────────────────┘          └─► audit log (no text, no values)
```

* **Categories:** `PASSWORD USERNAME EMAIL PHONENUMBER FIRSTNAME LASTNAME SSN CREDITCARDNUMBER CREDITCARDCVV IBAN ACCOUNTNUMBER STREET IPV4`.
* **Out of scope:** API keys and tokens, languages other than English, files, and deliberately obfuscated text ([docs/POLICY.md](docs/POLICY.md)).

**Key features of the application**

* **Employee workspace.** Paste a prompt and get ALLOW or BLOCK with the detected types. For a BLOCK, WASHQ shows a masked copy that can be copied, with a reminder to review it first.
* **Admin dashboard.** Number of scans, allowed and blocked counts, daily activity, the most detected types and the latest events.
* **Security logs.** A filterable audit log. It stores the time, decision, types and counts, and **never the text or the detected values**.
* **Fail-closed.** If the detector is not loaded or fails, the scan is shown as an error, never as ALLOW.
* **Local.** The model is loaded from a local folder, and the text is never sent to an external service.

## What was evaluated

| Component | Status |
|---|---|
| **Core detector**: the frozen **R3** checkpoint (`r2_e3b_positive`, fine-tuned mBERT) + **English rules v3**, `strict` mode | **The evaluated system**, frozen on 2026-10-24 ([configs/inference/frozen_system.json](configs/inference/frozen_system.json)). On the independent **Challenge v2** benchmark (400 unseen cases by a separate author, evaluated once): False ALLOW 2/200, False BLOCK 70/200, BLOCK F1 0.846, entity F1 0.677. |
| **Saudi supplemental rules** (Saudi mobile, national ID, iqama, e-mail; `backend/app/saudi_rules.py`) | **Demo only.** Never evaluated, and **not part of Challenge v2** or any reported result. They can add masked values. They never remove or relabel a core finding. |
| **Application**: FastAPI backend, HTML/CSS/JavaScript frontend, SQLite audit log | Software covered by automated tests; not an ML component. |

* Most false blocks are harmless look-alike identifiers, such as order, tracking, invoice and version numbers.
* No real employee prompts were evaluated.
* Details: [reports/FINAL_REPORT.md](reports/FINAL_REPORT.md). Risks and limits: [docs/RISKS.md](docs/RISKS.md), [backend/README.md](backend/README.md).

## Quick Start — Run WASHQ Locally

> **The original AI4Privacy training dataset and generated training/evaluation datasets are NOT required to run WASHQ.**
> You need only this repository, its Python packages and the trained R3 checkpoint from Google Drive (Step 4). See [Datasets are not required](#datasets-are-not-required).

These steps are for **Windows 10/11 with PowerShell**, preferably in VS Code.
* Run every command **in the repository folder** (`confidentiality-detector`).
* The first setup downloads about 250 MB of Python packages and the 659 MB checkpoint.
* Steps 1–4 are needed only once.

### Step 1 — Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Windows | 10 or 11, 64-bit (x64) | verified on Windows 11 x64 |
| Git | any recent version | https://git-scm.com/download/win |
| uv | 0.12.23 or newer | installs Python and the exact package versions of `uv.lock`; verified with 0.12.23 |
| Python | **3.13** | **Nothing to install:** uv uses an existing Python 3.13 or downloads one automatically (verified with 3.13.0 and 3.13.16). Python 3.12 and older do not work. |
| VS Code | recommended | https://code.visualstudio.com |
| Disk space | about 2.5 GB | Python environment ≈ 1 GB; checkpoint ZIP 0.66 GB, extracted 0.71 GB. The ZIP can be deleted after Step 4. |

Install Git and uv, for example with `winget`, or use the Git website and the [uv installation page](https://docs.astral.sh/uv/getting-started/installation/):

```powershell
winget install --id Git.Git -e --source winget
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then **close and reopen** PowerShell or VS Code so that the new commands are found, and check them:

```powershell
git --version
uv --version
```

Node.js is not needed; it is used only by an optional frontend test.

### Step 2 — Clone the repository

```powershell
cd $HOME
git clone https://github.com/nada00kh/confidentiality-detector.git
cd confidentiality-detector
code .        # optional: open the folder in VS Code
```

* This creates `C:\Users\<you>\confidentiality-detector`.
* Avoid folders synced by OneDrive (often Desktop and Documents), because OneDrive would also upload the 709 MB model.
* If Git asks you to sign in, or reports `Repository not found`, your GitHub account has not been given access to the repository yet.
* In VS Code, open a terminal with **Terminal → New Terminal**. It starts in the repository folder, in PowerShell.

### Step 3 — Create the Python environment

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # lets this window run the project script; nothing permanent
. .\scripts\dev_env.ps1 -Sync                                # Python 3.13 + the exact packages of uv.lock, then activates them
uv sync --frozen --inexact --group web                       # adds the web server packages (FastAPI, Uvicorn)
```

* **Type the leading dot and space** in `. .\scripts\dev_env.ps1`. They keep the environment active in this window. The script prints `confidentiality-detector environment: C:\Users\<you>\AppData\Local\confidentiality-detector\venv`.
* **Where the environment lives.** It is created in `%LOCALAPPDATA%\confidentiality-detector\venv`, outside the repository, so that sync clients such as OneDrive cannot interfere. The detector and the backend share this one environment; no separate backend environment is needed.
* **Exact versions.** `--frozen` installs exactly the versions in `uv.lock`, which are the libraries R3 was frozen and evaluated with: torch 2.14.1 (CPU), transformers 5.19.0, tokenizers 0.23.2. `--inexact` keeps the packages that are already installed.
  * Do not run `uv lock`, `uv add` or `pip install --upgrade`: they would change these versions.
  * `requirements.txt` is the same lockfile exported for pip, without the web packages. The uv commands above are the verified path.
* The first run takes a few minutes.
* **Every new terminal** needs these two lines before any other command, for example the second terminal in Step 6:

  ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  . .\scripts\dev_env.ps1
  ```

### Step 4 — Download the trained R3 checkpoint

The repository does **not** contain the model weights: they are 709 MB and git-ignored. They are provided separately in Google Drive, and access to this folder is required:

**Google Drive folder (WASHQ - Content & R3 Model):** https://drive.google.com/drive/folders/1JHfXdEwwmMoH1x_jVjDDzegdZQwl7xE_?usp=sharing

1. **Open the link.**
2. **Download only the file `r2_e3b_positive.zip`** (659 MB): right-click it, then **Download**.
   * Google Drive warns that it cannot scan a file this large for viruses; choose **Download anyway**.
   * Do not download the whole Drive folder: Drive would wrap the ZIP in another ZIP.
3. **Extract it into the repository's `checkpoints` folder.** The ZIP already contains a folder named `r2_e3b_positive`, so the destination is `checkpoints`, **not** `checkpoints\r2_e3b_positive`:

   ```powershell
   Expand-Archive -Path "$HOME\Downloads\r2_e3b_positive.zip" -DestinationPath checkpoints
   ```

   * Change the path if your browser saved the file somewhere else, or under another name such as `r2_e3b_positive (1).zip`.
   * **With File Explorer instead:** right-click the ZIP, choose **Extract All…**, then **Browse** to `C:\Users\<you>\confidentiality-detector\checkpoints`. Explorer suggests a destination ending in `\r2_e3b_positive`, which would create the nested folder shown below.
4. **Check the result:**

   ```powershell
   Get-ChildItem checkpoints\r2_e3b_positive      # six files, no subfolder
   python scripts/check_frozen_identity.py
   ```

   Expected structure:

   ```
   confidentiality-detector\
     checkpoints\
       r2_e3b_positive\
         config.json
         history.json
         model.safetensors        709,157,780 bytes
         tokenizer.json
         tokenizer_config.json
         training_summary.json
   ```

   * `check_frozen_identity.py` compares the files with the frozen record (sha256) without running the model. Its output must end with **`Same detector as the frozen record: yes`**.
   * On any computer other than the one the system was frozen on, two lines are expected and harmless: `runtime  differs: python 3.13.x (frozen 3.13.0)` and `Byte-identical frozen environment ...: no`.

**Nested folder.** This layout is wrong, and the model will not load:

```
checkpoints\r2_e3b_positive\r2_e3b_positive\config.json …
```

Fix it by moving the files up one level:

```powershell
Move-Item checkpoints\r2_e3b_positive\r2_e3b_positive\* checkpoints\r2_e3b_positive\
Remove-Item checkpoints\r2_e3b_positive\r2_e3b_positive
```

* **Do not change the folder's contents.** Do not rename, convert or add files: the identity check hashes every file in the folder.
* **Another location (optional).** The backend uses `checkpoints\r2_e3b_positive` by default, and no setting is needed. To keep the checkpoint elsewhere, set `WASHQ_MODEL_DIR` in the backend's terminal before every start (Step 5), and pass the same folder to the check:

  ```powershell
  $env:WASHQ_MODEL_DIR = "D:\models\r2_e3b_positive"
  python scripts/check_frozen_identity.py --model-dir "D:\models\r2_e3b_positive"
  ```

### Step 5 — Start the backend

In the terminal from Step 3, with the environment active, run this from the repository folder:

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

* **Starting the backend loads the R3 model into memory** (CPU). Wait for `Application startup complete.`: up to about a minute on the first start, a few seconds later.
* **Check it** at http://127.0.0.1:8000/health. Expected response:

  ```json
  {
    "status": "ready",
    "model_loaded": true
  }
  ```

* **`503` with `{"status": "not_ready", "model_loaded": false}`** means that the server runs but the model is not loaded.
  * Every scan will fail; it is never answered with ALLOW.
  * The terminal shows `Detector could not be loaded (...)` with the reason. It is usually a missing or wrongly extracted checkpoint ([Troubleshooting](#troubleshooting)).
  * After fixing it, stop the server with **Ctrl+C** and start it again. `/health` does not retry loading.
* **Leave this terminal running.** Interactive API documentation is at http://127.0.0.1:8000/docs.

### Step 6 — Start the frontend

Open a **second** terminal (VS Code: **Terminal → New Terminal**, or the **+** in the terminal panel), then run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\scripts\dev_env.ps1
python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Open **http://localhost:5500**.

* **No build step.** The frontend is plain HTML/CSS/JavaScript: no npm and no build. Python's built-in web server only serves the files.
* **The backend address.** The pages call the backend at `http://localhost:8000` (`frontend/js/config.js`).
* **Allowed addresses (CORS).** The backend accepts browser requests only from `http://localhost:5500` and `http://127.0.0.1:5500`.
  * If you open `index.html` by double-clicking it, or serve the pages from another port, every scan fails with "WASHQ couldn't scan this text".
  * This includes VS Code Live Server on a different port.
* **Leave this terminal running too.**

### Step 7 — Verify the application

1. On the welcome page, choose **Employee**.
2. In the workspace, paste each text below into the box and click the send button.

All values are fictional: `DE89 3704 0044 0532 0130 00` is the standard example IBAN used in documentation.

| # | Check | Expected result (verified 2026-11-01 on a fresh clone) |
|---|---|---|
| 1 | Harmless English prompt: `Draft a polite reply to a customer asking about a delayed refund.` | **ALLOW**: "Nothing sensitive", and the text is returned unchanged |
| 2 | Prompt with a sample IBAN: `Please wire the deposit to DE89 3704 0044 0532 0130 00 before Friday.` | **BLOCK**: "Sensitive data found · 1 item masked", type **IBAN × 1** |
| 3 | The masked copy in that BLOCK card | `Please wire the deposit to [IBAN] before Friday.`, with the note "Review the masked text before sharing. Automatic masking may miss sensitive information." |
| 4 | Dashboard: go back to the welcome page and choose **Administrator**, or open http://localhost:5500/admin.html | Total scans, Allowed and Blocked include your scans. **IBAN** appears under "Most detected data types" and in "Latest security events". |
| 5 | Backend unavailable: press **Ctrl+C** in the backend terminal, then scan any text | "WASHQ couldn't scan this text. Couldn't reach the WASHQ server at http://localhost:8000." The scan is never shown as ALLOW. Start the backend again to continue. |

* **Sample prompts.** The workspace start screen also offers four sample prompts.
* **Dashboard data.** The dashboard counts every scan stored in the local audit log `backend\data\washq.sqlite3` (metadata only, no text). To start with an empty dashboard, stop the backend and delete that file.

**Stop WASHQ:** press **Ctrl+C** in each of the two terminals (backend and frontend).

**Start again later:**
1. Open two terminals in the repository folder.
2. In each, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and `. .\scripts\dev_env.ps1`.
3. Run the command from Step 5 in one terminal and the command from Step 6 in the other.

**Optional: automated tests** (environment active):

```powershell
python -m pytest backend/tests -q     # API, masking, fail-closed behaviour, the real checkpoint
python -m pytest -q                   # the detector package
```

Results on a fresh clone with the checkpoint (2026-11-01):
* `backend/tests`: 263 passed, 3 xfailed (expected failures).
* Detector package: 158 passed, 4 skipped. The skipped tests need local research data that is not in Git.

## Datasets are not required

> **The original AI4Privacy training dataset and generated training/evaluation datasets are NOT required to run WASHQ.**

| | Running WASHQ (the Quick Start above) | Reproducing training or research experiments |
|---|---|---|
| **Purpose** | use the trained detector and the web application | rebuild the datasets, retrain on a GPU, re-run evaluations |
| **Needs** | this repository, the packages of `uv.lock` and the R3 checkpoint from Google Drive | additionally the English subset of `ai4privacy/pii-masking-200k`, the regenerated training and evaluation files, and a Google Colab GPU |
| **Data downloads** | none. The model loads only from `checkpoints\`, and inference downloads nothing. | the source dataset from Hugging Face |

**For the research pipeline:**
* [docs/DATASETS.md](docs/DATASETS.md): every dataset, its role, counts and sharing limits.
* [docs/DATA_PIPELINE.md](docs/DATA_PIPELINE.md): how the data was built.
* The source dataset: https://huggingface.co/datasets/ai4privacy/pii-masking-200k. Its dataset card states no licence, so the source data and files derived from it are not in this repository.

The research commands, for reference only (they need the raw data; training runs on Colab):

```bash
python scripts/build_synth_round2.py                               # round-2 generated data
python scripts/build_eval_sets.py --policy v3 --out data/eval_v3   # round-2 evaluation suite (needs the raw data)
python scripts/make_colab_bundle.py --round round2                 # then notebooks/colab/06_round2_experiments.ipynb on a GPU
python scripts/evaluate_system.py --results results/round2 --detail
```

## Troubleshooting

| Problem | What to do |
|---|---|
| `running scripts is disabled on this system` | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that window, then repeat the command. It applies to that window only. |
| `uv` or `git` is not recognized | Close and reopen PowerShell or VS Code after installing them, then check with `uv --version`. |
| **Python version mismatch**: `python --version` is not 3.13, or uv reports that no Python 3.13 was found | <ul><li>If `python --version` shows another version, the environment is not active in this window: run `. .\scripts\dev_env.ps1`, with the dot and space.</li><li>If uv cannot download Python (offline, a proxy, or downloads disabled), run `uv python install 3.13`, or install Python 3.13 from python.org, then repeat Step 3.</li></ul> |
| **Missing dependencies**: `No module named uvicorn` or `fastapi` | With the environment active, run `uv sync --frozen --inexact --group web`. |
| **Missing dependencies**: `No module named torch` or `confidentiality_detector` | The environment is not active, or Step 3 did not finish. Run `. .\scripts\dev_env.ps1 -Sync`, then the `--group web` command again. Do not install other versions with pip. |
| **Missing checkpoint**: `Detector could not be loaded (FileNotFoundError: checkpoint folder not found: ...)` | Do Step 4. The folder must be exactly `checkpoints\r2_e3b_positive`, or set `WASHQ_MODEL_DIR`. |
| **Incorrect extraction path**: `Detector could not be loaded (ValueError: Couldn't instantiate the backend tokenizer ... sentencepiece or tiktoken ...)`, or `check_frozen_identity.py` prints `...\r2_e3b_positive: no .safetensors weights` | The files are not directly in `checkpoints\r2_e3b_positive`; usually it is the nested folder. **Do not install sentencepiece.** Move the files up (Step 4), then restart the backend. |
| `check_frozen_identity.py` prints `checkpoint files   DIFFERS: ...` | <ul><li>`missing`: the extraction is incomplete.</li><li>`not in the frozen record: desktop.ini` (or another file): delete that file.</li><li>`sha256 differs`: the download is damaged; download and extract it again.</li></ul> |
| **Backend not ready**: `/health` returns `503 not_ready` | Read the `Detector could not be loaded (...)` line in the backend terminal and fix the cause (rows above). Then stop the backend with Ctrl+C and start it again. |
| **Port 8000 occupied**: `[Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000)` | Usually an earlier WASHQ backend is still running in another terminal: stop it with Ctrl+C. To see which program holds the port: `Get-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess` |
| **Port 5500 occupied**: `PermissionError: [WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions` | <ul><li>Often VS Code **Live Server** ("Go Live"), which also uses port 5500: stop it from the VS Code status bar, or close the other program (same `Get-NetTCPConnection` command as above, with `5500`).</li><li>To use another port, for example 5501: before starting the backend, run `$env:WASHQ_CORS_ORIGINS = "http://localhost:5501,http://127.0.0.1:5501"` in the backend terminal. Then start the frontend with `5501` instead of `5500`, and open http://localhost:5501.</li></ul> |
| **Frontend cannot connect to the backend**: "WASHQ couldn't scan this text. Couldn't reach the WASHQ server at http://localhost:8000." | <ul><li>The backend is not running or not ready: check http://127.0.0.1:8000/health.</li><li>The page was opened as a file, or from a port the backend does not allow: use http://localhost:5500.</li><li>The backend runs on a port other than 8000; the frontend expects 8000 (`frontend/js/config.js`).</li><li>A VPN, proxy or security tool that intercepts `localhost` can also block it.</li></ul> |
| A scan is slow | Scans run on the CPU, one at a time, and long texts (up to 10,000 characters) can take several seconds. The page waits up to 60 seconds, then shows an error, never a result. |

## Use the detector without the web application

```powershell
"Please wire the deposit to DE89 3704 0044 0532 0130 00" | python -m confidentiality_detector --model-dir checkpoints/r2_e3b_positive --mode strict
```

* **Output.** The command prints the decision as JSON: categories, positions and reason, never the values.
* **Exit status.** 0 = ALLOW, 10 = BLOCK, 2 = the detector could not be loaded.
* **The Python interface** (`ConfidentialityDetector.load(...).inspect(text, "strict")`) is described in [docs/INTEGRATION.md](docs/INTEGRATION.md) §2.

## Documentation

| Topic | Document |
|---|---|
| **The WASHQ application**: API, settings (`WASHQ_*` variables), what masking can and cannot guarantee, known limits, tests | [backend/README.md](backend/README.md) |
| The frontend pages, sample prompts, offline demo (mock) mode | [frontend/README.md](frontend/README.md) |
| **Final results**: system, development evidence, Challenge v2, strict vs maximum, model card | [reports/FINAL_REPORT.md](reports/FINAL_REPORT.md) |
| Checkpoint files and sha256 values, setup on another computer, Python interface, frozen files | [docs/INTEGRATION.md](docs/INTEGRATION.md) |
| Product purpose, scope, person-name policy, BLOCK/ALLOW logic, trade-offs | [docs/POLICY.md](docs/POLICY.md) |
| Modules and the inference data flow | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Datasets and the data pipeline | [docs/DATASETS.md](docs/DATASETS.md), [docs/DATA_PIPELINE.md](docs/DATA_PIPELINE.md) |
| Training, evaluation, selection rule, window and gate studies | [docs/METHODOLOGY.md](docs/METHODOLOGY.md) |
| Baselines (regex, rules, NER-only, hybrid) | [reports/BASELINE_AUDIT.md](reports/BASELINE_AUDIT.md) |
| What is and is not proven; security risks | [docs/RISKS.md](docs/RISKS.md) |
| Manual integration and demo test plan | [docs/INTEGRATION_TEST_PLAN.md](docs/INTEGRATION_TEST_PLAN.md) |
| Annotation rules, case-file format, Challenge v2 specification | [docs/ANNOTATION_GUIDELINES.md](docs/ANNOTATION_GUIDELINES.md), [docs/CASE_FORMAT.md](docs/CASE_FORMAT.md), [docs/CHALLENGE_V2_SPEC.md](docs/CHALLENGE_V2_SPEC.md) |
| Round reports, evidence and artifacts kept outside Git | [reports/README.md](reports/README.md), [reports/ARTIFACTS.md](reports/ARTIFACTS.md) |

## Repository layout

```
backend/                        WASHQ API (FastAPI): frozen-detector adapter, Saudi demo rules, masking, audit log
frontend/                       WASHQ pages (static HTML/CSS/JavaScript)
src/confidentiality_detector/   the detector package: model, rules v3, policy, pipeline, metrics
configs/                        inference/policy.json and frozen_system.json (the frozen system); experiments/*.json
scripts/                        setup (dev_env.ps1), identity check, data, evaluation and Challenge v2 tools (scripts/README.md)
checkpoints/                    model weights, local only (git-ignored); Step 4
data/                           hand-written sets, split ids and manifests; third-party data stays local (data/README.md)
docs/, reports/                 documentation, final report, evidence
notebooks/colab/, archive/      GPU training rounds (Colab); the original exploration notebooks
tests/                          tests of the detector package (backend tests: backend/tests/)
```

## Licence and data terms

* **No licence file.** The repository has none yet.
* **Base model:** `google-bert/bert-base-multilingual-cased`, Apache-2.0.
* **Training data:** `ai4privacy/pii-masking-200k`, whose dataset card states no licence.
  * Third-party data and data derived from it are therefore kept out of Git.
  * Redistribution of the fine-tuned weights beyond the project team is unresolved ([docs/INTEGRATION.md](docs/INTEGRATION.md) §9).
