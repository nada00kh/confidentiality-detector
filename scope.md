# Scope

**The authoritative definition is [`docs/POLICY.md`](docs/POLICY.md).** If anything here disagrees with it, `docs/POLICY.md` is right. This page is a summary.

Confidentiality Detector inspects an **English** prompt **locally**, before it is sent to an external LLM, and decides **BLOCK** or **ALLOW**.

* **Categories (exactly 13):** PASSWORD, USERNAME, EMAIL, PHONENUMBER, FIRSTNAME, LASTNAME, SSN, CREDITCARDNUMBER, CREDITCARDCVV, IBAN, ACCOUNTNUMBER, STREET, IPV4 (`labels.TARGET_LABELS`; POLICY §2).
* **Decision:** BLOCK if any of them is found; otherwise ALLOW. False ALLOW (leakage) is the primary concern and False BLOCK (friction) the secondary one (POLICY §1, §5).
* **Fail closed:** inputs over 100,000 characters, or inspection errors, are blocked, with an explanation that does not claim a detection.
* **Modes:** `strict` (default) and `maximum` (more recall, more false blocks).
* **Policy details:**
  * names of public figures are names (POLICY §3);
  * a 3–4 digit number is a CVV only with contextual evidence (POLICY §4);
  * explanations give categories and positions, never values (POLICY §7).
* **Out of scope:**
  * API keys, access tokens and other credentials (counted as false positives if flagged);
  * other languages, files and attachments;
  * deliberately obfuscated data (`docs/RISKS.md`).
* **Detector:** the fine-tuned mBERT model R3 (`r2_e3b_positive`) plus deterministic rules v3 (`docs/ARCHITECTURE.md`).

The project's original Arabic, regex-based scope is preserved for history in `archive/scope_original.md`. It does not describe the current system.
