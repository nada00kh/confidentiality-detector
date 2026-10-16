# Project Scope — Confidentiality Detector

## 1. Project Overview

Confidentiality Detector is an AI-based system designed to detect sensitive company information in text before it is shared with external AI services, such as LLM APIs.

The system processes text locally and returns a `BLOCK` or `ALLOW` decision, along with the detected sensitive data categories.

## 2. Input & Language Support

- **Input type:** Text only.
- **Primary language:** Arabic.
- Support Arabic text containing English-formatted identifiers, credentials, and other sensitive values.
- Full English-language support and bilingual evaluation are outside the initial scope.

## 3. Supported Sensitive Data Categories

The initial version targets 11 entity categories.

| Group | Entity Labels |
|---|---|
| Personal Information | `national_id`, `iqama`, `private_phone`, `private_email`, `employee_id` |
| Financial Information | `account_number`, `credit_card` |
| Technical Secrets | `password`, `api_key`, `access_token`, `db_connection` |

These categories define the overall system scope. Individual detection methods are not required to support every category independently.

## 4. Dataset

- **Primary dataset:** `mabahboh/sitr-arabic-pii`
- Prepare and filter the dataset according to the 11 selected entity categories.
- Use annotated data for model training and evaluation.
- Use the dataset's original training, validation, and test splits without re-splitting.

## 5. Detection Methods

### Regex Baseline

Develop a rule-based detector using regular expressions to identify sensitive information with recognizable patterns.

### Fine-tuned NER

Fine-tune a pretrained language model for token classification to detect sensitive entities in Arabic text.

The final model will be selected based on experimentation and available computing resources.

### Hybrid Detection

Combine Regex and NER detection results, including handling overlapping or conflicting predictions.

## 6. Local Processing

- Sensitive data detection must be performed locally.
- Input text must not be sent to external APIs or cloud-based AI services for detection.
- The detection pipeline will run within the project's local environment.

## 7. Decision Logic

The initial version uses a binary decision mechanism:

- `BLOCK` if sensitive information from the supported categories is detected.
- `ALLOW` if no supported sensitive information is detected.

The system provides the detected entity categories and explains the reason for blocking without exposing the original sensitive values.

## 8. Web Interface & API

- Provide a web interface for employees to submit text for confidentiality checks.
- Develop an API endpoint that processes submitted text.
- Return a `BLOCK` or `ALLOW` decision along with detected entity categories.
- Display detection results without revealing sensitive values.

## 9. Model Evaluation

- Evaluate Regex, Fine-tuned NER, and Hybrid detection on the same held-out dataset.
- Measure entity-level Precision, Recall, and F1-score.
- Measure message-level Precision, Recall, F1-score, and Accuracy for `BLOCK` / `ALLOW` decisions.
- Report per-category performance across the 11 supported entity types.
- Analyze false positives and false negatives.

## 10. Demo

- Demonstrate the system locally.
- Use the web interface connected to the detection API.
- Demonstrate both `BLOCK` and `ALLOW` decisions using sample Arabic texts.
- Display detected entity categories without exposing sensitive values.

## 11. Planned Additional Feature

### Admin Dashboard

Develop a simple monitoring dashboard for administrators to:

- View total scans and `BLOCK` / `ALLOW` statistics.
- Monitor the most frequently detected sensitive data categories.
- Review recent detection events.
- Track detection activity without storing original sensitive text or credentials.

This feature is planned but may be deferred if time is insufficient.

## 12. Optional Enhancements

The following improvements may be considered after completing the core functionality:

- **Presidio Integration:** Integrate Microsoft Presidio with the detection pipeline.
- **Vector Database:** Explore semantic retrieval of relevant security policies.
- **Risk-Based Classification:** Introduce risk levels for sensitive information.
- **LLM Integration:** Explore secure prompt handling using sensitive data masking.
