# Integration handoff: second computer, frontend and API

This page is for the developer who connects the existing HTML/CSS/JavaScript frontend and FastAPI backend to the detector, and for anyone who sets the project up on another computer.

* **Existing** (verified against the code): §1 setting up a computer, §2 the Python interface, §8 the frozen components. The detector is the frozen system of `configs/inference/frozen_system.json` (code commit `4907107`, unchanged since).
* **Implemented** (commit `0426942`, 2026-10-27; verified 2026-10-30): the WASHQ application in `backend/` (FastAPI) and `frontend/`.
  * **`backend/README.md`** covers setup and running it, which component was evaluated (the core detector) and which is a demo-only extension (the Saudi rules), what masking can and cannot guarantee, and the known limits.
  * §3–§7 below were written before the integration, as requirements. Each now notes how the application meets them.

## 0. Ground rules

* **The application uses `strict`.** `maximum` stays in the code and in `configs/inference/policy.json` for reproducibility and research. It is not offered to users, and the mode is never taken from a request (§2.2).
* **The frozen detector is not changed** during integration: no edits, reformatting or line-ending changes to the files in §8, no retraining, no new thresholds or gates. A change there is a new system that would need a new evaluation.
* **The checkpoint is not in Git**, and Git LFS is not used. It is shared privately (§1.2) and stays git-ignored in `checkpoints/`.
* **No real personal data** in fixtures, tests, logs or screenshots: only synthetic values (555-01xx phone numbers, invented names, public test card numbers).
* **The hidden `challenge_v2` cases are never in the repository**, and neither are per-case results. Only the four aggregate files in `reports/challenge_v2/` are shared.

## 1. Setting up a computer

Windows PowerShell commands; on macOS/Linux use the `uv sync` variant and `source .venv/bin/activate`.

### 1.1 Get the repository

```powershell
git clone <repository URL>
cd confidentiality-detector
```

### 1.2 Get the checkpoint from the private Google Drive folder

The project owner shares the folder `r2_e3b_positive` privately. Its link is deliberately not recorded in the repository.

1. Download the whole folder. Google Drive delivers it as a zip file, for example `r2_e3b_positive-<date>-001.zip`, of about 660 MB.
2. Extract it so that the six files sit **directly** in `checkpoints/r2_e3b_positive/`:

   ```
   confidentiality-detector/
     checkpoints/
       r2_e3b_positive/
         config.json  history.json  model.safetensors  tokenizer.json  tokenizer_config.json  training_summary.json
   ```

   * Windows "Extract All" often creates an extra folder level (`r2_e3b_positive/r2_e3b_positive/…`); move the files up.
   * Remove anything else in the folder (for example a `desktop.ini` added by a sync client). The frozen identity hashes every file in the folder.
   * Do not rename, re-save or convert any file.

| File | Bytes | sha256 (from `configs/inference/frozen_system.json`) | Needed for |
|---|---|---|---|
| `model.safetensors` | 709,157,780 | `dc0fdca52f9e144b4017cb8eb37d8cef0d366b5b9619c519a782102ef32850c6` | inference |
| `config.json` | 2,139 | `f5132da68b978b176383f7ee25d86215727701a9a05aeb534ea9746d6d29a13e` | inference (architecture, 27 BIO labels) |
| `tokenizer.json` | 2,919,362 | `bf1b59b7b11c95f194f51708d918eea378e09d05f84c0e1656dc5180e8117088` | inference |
| `tokenizer_config.json` | 352 | `9cd988573a9588a6085cd353eeefa09b803dba75b03f58d0c1d302aad3078193` | inference |
| `training_summary.json` | 3,737 | `072fd554519ad1041309027e29ba74781dcf7a94b188aad26f1d3e8e0036c704` | provenance; part of the frozen identity |
| `history.json` | 1,671 | `c0d0760b591b7a32a883406c9c815c36dc6d009b3301aa9a5ff79baab7428f91` | provenance; part of the frozen identity |

The model is loaded only from this folder (`local_files_only=True`). Inference never downloads anything from Hugging Face or any other service.

### 1.3 Install the environment

Prerequisites: Git and [uv](https://docs.astral.sh/uv/getting-started/installation/). uv installs Python 3.13 if needed and the exact package versions of `uv.lock`.

```powershell
. .\scripts\dev_env.ps1 -Sync     # first time: environment in %LOCALAPPDATA%\confidentiality-detector\venv, then activated
. .\scripts\dev_env.ps1           # every later PowerShell session
```

* The script keeps the environment outside the repository, which is required when the repository is in a OneDrive-synced folder and harmless otherwise.
* If PowerShell refuses to run the script, allow scripts for the current session only: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.
* Alternative, outside synced folders: `uv sync --frozen`, then `.\.venv\Scripts\Activate.ps1`.
* Always use `--frozen` (or the script), so that `uv.lock` is not re-resolved.

### 1.4 Verify the checkpoint and the detector identity

```powershell
python scripts/check_frozen_identity.py
```

It runs no model and reads no evaluation data. Expected on a correctly set-up computer:

```
checkpoint files   OK  6 files, model.safetensors dc0fdca52f9e…
policy file        OK
rules version      OK  v3
inference windows  OK  512/64/first
inference code     OK  12 files (11 with other line endings than on the freezing computer)
runtime            OK  same Python and library versions        <- or "differs: python 3.13.x (frozen 3.13.0)"

Same detector as the frozen record: yes
```

Exit status 0 means: the same checkpoint bytes, policy, rules, windows and code content as the frozen system. For the weights alone, compare with the table above:

```powershell
(Get-FileHash checkpoints\r2_e3b_positive\model.safetensors -Algorithm SHA256).Hash   # DC0FDCA52F9E144B…
```

### 1.5 Smoke test (synthetic text)

```powershell
"Please summarise the attached meeting notes for the team." | python -m confidentiality_detector --model-dir checkpoints/r2_e3b_positive --mode strict
# "decision": "ALLOW", "reason": "NO_SENSITIVE_ENTITIES"; exit code 0
"Hi, please log in as jdoe with password Zq81kLm!x and call Mira Okafor on 555-0142." | python -m confidentiality_detector --model-dir checkpoints/r2_e3b_positive --mode strict
# "decision": "BLOCK", categories FIRSTNAME, LASTNAME, PASSWORD, PHONENUMBER, USERNAME; exit code 10
```

These outputs were produced on the frozen environment on 2026-10-25. Then run the tests:

```powershell
python -m pytest -q
```

Everything passes. A few tests skip because they need git-ignored local data (the original notebooks' processed datasets, the regenerated Round 2 files) or the byte-identical frozen environment (§1.6). The test fixture `tiny_checkpoint` downloads the public mBERT tokenizer from Hugging Face once, or skips if offline. That is a test only, never inference.

### 1.6 Same detector versus strict reproduction of the frozen environment

| | Requires | On a second computer |
|---|---|---|
| **Same detector**: `scripts/check_frozen_identity.py` exits 0 | the six checkpoint files byte for byte; the policy file; the code content; rules v3; windows 512/64/first | **expected**: Git keeps `configs/` byte-exact, and the libraries come from `uv.lock` |
| **Byte-identical frozen environment**: `scripts/challenge_v2.py verify-frozen` | also the code bytes, including line endings; Python 3.13.0 exactly; and a re-run of the recorded decisions on `dev_v1` and `test_long` | **not expected**: see below |

Why `verify-frozen` refuses on a fresh clone, although the detector is the same:
* **Line endings.** The frozen hashes are of the files on the freezing computer, where 11 of the 12 hashed code files have LF and `detectors/transformer.py` has CRLF endings. A clone gets the platform's line endings: CRLF on Windows (`.gitattributes` `text=auto`), LF elsewhere. This was measured on fresh clones on 2026-10-25: identical up to line endings, 12/12; byte-identical, 1/12. Python reads both identically.
* **Python patch level.** `uv.lock` pins every library (torch 2.14.1, transformers 5.19.0, tokenizers 0.23.2, safetensors 0.8.0, numpy 2.4.6, phonenumbers 9.0.40), but not the Python patch release (frozen: 3.13.0).
* **Data.** `test_long` is derived from the third-party training data and is not in Git (`docs/DATA_PIPELINE.md`).

So `verify-frozen` and the end-to-end frozen-system test belong to the freezing computer. On any other computer the evidence is `check_frozen_identity.py` plus the consistency checks in §7.

Decisions on another computer are expected to be identical, but this has not been measured. Different CPUs, operating systems or a GPU can change model probabilities in the last digits, which could flip a borderline token. Use `device="cpu"` (§2.1) for the configuration that was evaluated.

## 2. The existing Python interface

All of this is in `src/confidentiality_detector/` and unchanged since the freeze.

### 2.1 Loading, once per process

```python
from confidentiality_detector.pipeline import ConfidentialityDetector

detector = ConfidentialityDetector.load(
    "checkpoints/r2_e3b_positive",          # model_dir
    "configs/inference/policy.json",        # policy_path: modes, max_chars, fail-closed settings, windows
    device="cpu",                            # None picks CUDA when available; "cpu" is the evaluated configuration
)
```

* `load` reads the policy, loads the fast tokenizer and the weights from the folder (`local_files_only=True`), and refuses a checkpoint with missing or mismatched weights, a wrong label mapping or windows the model cannot take.
* It **raises** on failure (missing folder or file, corrupt weights, invalid policy). There is no fallback detector.
* Loading takes seconds and keeps about 0.7 GB of weights in memory, so load once at start-up, not per request.

### 2.2 Inspecting text

```python
decision = detector.inspect(text, "strict")                 # always pass "strict" explicitly
decisions = detector.inspect_batch([text1, text2], "strict")
```

* `mode=None` would use the policy default, which is `strict` today. Passing `"strict"` keeps the application independent of that default.
* **Never pass a mode from user input.** An unknown mode raises `ValueError`, and `"maximum"` is not a product option.

### 2.3 The result

`Decision` (`policy.py`) holds:
* `decision` (`"BLOCK"`/`"ALLOW"`) and `blocked` (bool);
* `reason`;
* `mode`;
* `categories`: the sorted labels found;
* `findings`: `Finding(start, end, label, source, score)`, where `source` is `model`, `rules` or `model+rules`;
* `policy_version`.

`explanation()` gives a user-facing sentence, and `to_dict()` a JSON-safe dict. Neither contains the text or any value:

```json
{
  "decision": "BLOCK", "reason": "SENSITIVE_ENTITIES", "mode": "strict",
  "categories": ["FIRSTNAME", "LASTNAME", "PASSWORD", "PHONENUMBER", "USERNAME"], "policy_version": "1.0",
  "findings": [{"start": 22, "end": 26, "label": "USERNAME", "source": "rules", "score": 0.8},
               {"start": 41, "end": 50, "label": "PASSWORD", "source": "model+rules", "score": 1.0}, "…"],
  "explanation": "BLOCK: the text contains information in protected categories: FIRSTNAME (1), LASTNAME (1), PASSWORD (1), PHONENUMBER (1), USERNAME (1). Character positions: 22-26, 41-50, 60-64, 65-71, 75-83."
}
```

| `reason` | `decision` | When |
|---|---|---|
| `SENSITIVE_ENTITIES` | BLOCK | at least one finding in the 13 categories |
| `NO_SENSITIVE_ENTITIES` | ALLOW | no finding |
| `EMPTY_INPUT` | ALLOW | empty or whitespace-only text |
| `INPUT_TOO_LARGE` | **BLOCK** (fail closed) | more than 100,000 characters (`max_chars`) |
| `INSPECTION_ERROR` | **BLOCK** (fail closed) | any exception inside detection; logged with the exception type only |

**What raises instead of failing closed** (the caller must handle it, §3):
* `TypeError`: the text is not a `str`;
* `ValueError`: an unknown mode;
* exceptions from `load`.

### 2.4 Command line and logging

* **CLI:** `python -m confidentiality_detector --model-dir DIR [--mode strict] [--file F | stdin]`, or the `confidentiality-detector` console script. It prints `to_dict()` as JSON. Exit status: 0 = ALLOW, 10 = BLOCK, 2 = the detector could not be loaded.
* **Logging:** the logger `confidentiality_detector` writes at INFO, per text: the decision, reason, mode, categories, number of findings, input length, batch latency and model name. On errors it writes at ERROR, with the exception type only. It never logs text or values.

## 3. Fail-closed duties of the application (required)

The detector fails closed inside `inspect`. The application must keep that guarantee around it:

1. **The detector is unavailable.** If `load` fails at start-up, the service must not answer ALLOW. Either refuse to start, or answer every request as BLOCK.
2. **Errors anywhere.** The frontend treats any error as BLOCK and does not send the prompt on: a network failure, a timeout, a non-success status or a response it cannot parse.
3. **Invalid requests.** A body without a text string must be refused, never inspected as `str(...)`. The refusal counts as BLOCK in the frontend.
4. **Size.** The detector blocks texts over 100,000 characters (`INPUT_TOO_LARGE`). A web-server body limit below that would turn large inputs into errors, which point 2 then treats as BLOCK.
5. **Empty text** is ALLOW by policy (`EMPTY_INPUT`).

**In the application** (`backend/app/main.py`, `frontend/js/workspace.js`):
1. **Detector unavailable.** If loading fails, the server still starts, but every scan answers 503, and `/health` answers 503 `not_ready`. When the detector is loaded, `/health` answers 200 `ready`.
2. **Errors anywhere.** A network failure, a non-OK status, an incomplete answer, or no answer within 60 seconds (`CHECK_TIMEOUT_MS`) shows "WASHQ couldn't scan this text".
   * No result is shown, and there is nothing to copy.
   * The text is never presented as safe.
   * A timed-out request is cancelled, and a late answer is ignored.
3. **Invalid requests.** Rejected with 422 before inspection.
4. **Size.** The API accepts at most 10,000 characters (422 above that). The detector's `INPUT_TOO_LARGE` path is therefore not reached through the API; the adapter would turn it into a 503.
5. **Empty or blank text.** Rejected with 422, and the workspace does not submit it. This differs from the detector's own `EMPTY_INPUT` ALLOW.

## 4. Never expose detected values (required)

**In the application**, values are never logged or stored, and 422 messages never echo the input. One requirement below was changed by design:
* The API **returns text**: the user's own text unchanged for ALLOW, or a masked copy for BLOCK, with every detected value replaced.
* It also returns positions (UTF-16), which the browser uses for its masking animation.
* The masked copy can still contain values the detectors missed, so the workspace asks the user to review it before sharing (`backend/README.md`).


* **Return** `decision.to_dict()`, or a subset of it. Never return the input text or any substring of it, and never derive one from the offsets on the server.
* **Offsets locate values.** Start/end plus the original text reveal the value. Never store or log them together with the text. Whether the frontend highlights the positions in the user's own browser is a product decision; if it does, nothing leaves the page.
* **Logging and errors:**
  * Do not log request or response bodies.
  * Do not enable debug middleware or error trackers that capture request data or local variables.
  * FastAPI's default validation-error response (HTTP 422) echoes the offending input. Replace it with a handler that returns no input.
* **No external calls.** Do not send the text anywhere: no telemetry or analytics that see it, and no LLM call before the decision is ALLOW.

## 5. Running it in a web service

The application follows these recommendations:
* It loads the detector once at start-up.
* FastAPI runs the synchronous check handler in a worker thread.
* `ModelDetector` serialises calls with one lock.
* The paths are configurable (`backend/README.md`).


* **Load once** at start-up (§2.1), and share one `ConfidentialityDetector`.
* **The call is CPU-bound and blocking.** Run it in a worker thread, not directly in an `async` handler.
* **Serialise calls** (for example with one `threading.Lock`). The shared fast tokenizer has not been verified for concurrent use, and an exception there would surface as a spurious `INSPECTION_ERROR` BLOCK.
* **Expected latency** (Round 1 measurement, laptop CPU): about 37 ms median per short prompt, 0.6–2.9 s for 600–1,000-token documents.
* **Configurable paths.** Make the checkpoint and policy paths configurable, defaulting to the repository-relative paths above. Never hard-code a personal path.

## 6. Integration workflow

Steps 1–5 were completed with commit `0426942`, which was added to `main` directly rather than through a feature branch. On 2026-10-30:
* the step 6 checks passed;
* both test suites passed;
* `check_frozen_identity.py` exited 0;
* there was no diff under `src/confidentiality_detector` or `configs/inference`.

The original plan:

1. The project owner pushes `main` with the finalised detector.
2. The integrating developer clones it and completes §1 on her computer. `check_frozen_identity.py` must exit 0.
3. She creates a feature branch from `main` (`git switch -c feature/frontend-api-integration`) and adds the existing frontend and FastAPI code in its own top-level folder(s).
4. **Dependencies:**
   * Add the web dependencies as a separate uv dependency group (`uv add --group <name> …`), and review the `uv.lock` diff.
   * The six libraries in §1.6 must keep their versions; `check_frozen_identity.py` reports any change under `runtime`.
   * `pyproject.toml` and `uv.lock` change only through that addition.
5. Add the consistency test of §7 and the run instructions for the application, in this page or the README.
6. **Before the pull request:**
   * `python -m pytest -q` passes;
   * `python scripts/check_frozen_identity.py` exits 0;
   * `git diff --stat main -- src/confidentiality_detector configs/inference` is empty;
   * no checkpoint, `challenge_v2` or personal file is staged.
7. Both developers review and merge, then each runs the complete application locally on their own computer.

## 7. API/CLI consistency check

The API must return exactly the decision that direct inference gives, on new synthetic fixtures. Never use the `challenge_v2` cases or real prompts.

**Implemented** in `backend/tests/test_saudi_extension.py` and `test_real_model.py::test_api_matches_direct_inference`. Two things differ from the outline below:
* **Response shape.** The API has its own response shape (type codes such as `PERSON_NAME`, not the detector's `to_dict()`). The comparison is therefore on `decision` and the `(start, end, type)` of every masked span.
* **Two comparisons.** The application adds the Saudi demo extension, so the comparison is made twice:
  * with the **core detector alone**, the API equals direct `strict` inference;
  * with the **full application**, the result equals the core result plus the Saudi findings. Those can only add masked values, and they never change a core finding's type.
  * Where a Saudi rule also matches a core-typed value, the separate `pattern_hints` field explains it as a demo-rule format match. Hints change nothing else, and they are not stored.
  * The full application is therefore **not** identical to the evaluated detector, and must not be described as such.

* **Fixtures:**
  * Put them in a new file, for example `tests/fixtures/integration_synthetic.jsonl`, with fictional values only.
  * Cover harmless text and at least one text per category.
  * Include look-alikes such as tracking numbers and version strings. Their false blocks are known (`reports/FINAL_REPORT.md` §5) and must be reproduced, not "fixed".
  * Include structured text (JSON, SQL, a log line), non-ASCII text, an empty text and a text over 100,000 characters.
* **Test:** for each text, compare the API response with `detector.inspect(text, "strict").to_dict()`. `decision`, `reason`, `mode`, `categories` and the `(start, end, label)` of every finding must be equal. In outline (the route and request format are hers to define):

  ```python
  direct = detector.inspect(text, "strict").to_dict()
  answer = call_api(text)                     # placeholder: her FastAPI route, e.g. through fastapi.testclient.TestClient
  assert {k: answer[k] for k in ("decision", "reason", "mode", "categories")} == {k: direct[k] for k in ("decision", "reason", "mode", "categories")}
  assert [(f["start"], f["end"], f["label"]) for f in answer["findings"]] == [(f["start"], f["end"], f["label"]) for f in direct["findings"]]
  ```

* **CLI:** run the same texts through `python -m confidentiality_detector --mode strict`, and compare the JSON and the exit code (0/10).
* **Fail-closed cases:** simulate a detector that raises, and an unloadable checkpoint, and check that the API and the frontend end in BLOCK.
* **Both computers:** run the test on both. Identical results on both are the practical evidence of portability (§1.6).

## 8. Frozen components: do not modify

| Path | Why |
|---|---|
| `checkpoints/r2_e3b_positive/` (not in Git) | model weights, tokenizer, configuration; sha256 in the frozen record |
| `configs/inference/policy.json` | modes, `max_chars`, fail-closed settings, windows 512/64/first |
| `configs/inference/frozen_system.json` | the frozen record itself |
| `src/confidentiality_detector/`: `__init__.py`, `__main__.py`, `alignment.py`, `decoding.py`, `documents.py`, `labels.py`, `pipeline.py`, `policy.py`, `detectors/__init__.py`, `detectors/hybrid.py`, `detectors/rules.py`, `detectors/transformer.py` | the inference code, rules v3 included, hashed in the frozen record |
| `uv.lock`, `pyproject.toml` | runtime versions; only the additive dependency group of §6 |

* Do not run formatters or line-ending normalisation (`git add --renormalize`, editor "convert line endings") on these files.
* Do not use `git checkout -- <file>`, `git reset --hard` or `git stash` on them in the owner's working copy. These rewrite the files and break the byte-level identity there (§1.6).
* Evaluation tooling (`challenge.py`, `metrics.py`, `scripts/challenge_v2.py`) is not part of the frozen identity. Their sha256 at evaluation time is recorded in `reports/challenge_v2/LEDGER.jsonl`, so they should not change either.

## 9. Provenance and licensing of the checkpoint

* **Base model:** `google-bert/bert-base-multilingual-cased`, Apache-2.0 (model card, checked 2026-10-25).
* **Fine-tuning data:** the English subset of `ai4privacy/pii-masking-200k`, plus augmented copies and synthetic documents generated by this project. The dataset card (checked 2026-10-25) states **no licence**. The copy used came from an intermediate Hub repository whose name was not recorded (`docs/DATA_PIPELINE.md` §0).
* **Consequence:** whether the fine-tuned weights may be redistributed beyond the project team is **unresolved**. Keep the checkpoint in private, access-controlled storage, and clarify the dataset's terms with its authors (or the supervising institution) before any public release of the weights or of data derived from it.
