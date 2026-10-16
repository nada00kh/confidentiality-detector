# Confidentiality Detector

## Overview

Confidentiality Detector is an AI-based system designed to prevent sensitive company information from being exposed when using external AI services, such as LLM APIs.

The system analyzes text to identify sensitive information and returns a `BLOCK` or `ALLOW` decision before the data is shared.

The current implementation includes a rule-based detection baseline using regular expressions (Regex).

## Current Implementation

The project currently includes a rule-based PII detection baseline with:

- Regex-based detection for emails, Saudi phone numbers, national IDs, and Iqama numbers.
- Support for Arabic-Indic and Persian digit normalization.
- Entity extraction with labels and character offsets.
- `BLOCK` / `ALLOW` decisions based on detected entities.
- Entity-level and message-level evaluation metrics.
- Automated unit tests using Pytest.

## Project Structure

```text
confidentiality-detector/
├── evaluation/
│   └── metrics.py
├── notebooks/
│   ├── 01_initial_data_exploration.ipynb
│   ├── 02_baseline_benchmark.ipynb
│   └── 02_scoped_data_EDA.ipynb
├── src/
│   ├── detectors/
│   │   ├── regex_detector.py
│   │   ├── ner_detector.py
│   │   └── presidio_detector.py
│   ├── pipeline.py
│   └── risk_engine.py
├── tests/
│   ├── test_evaluation.py
│   └── test_regex_baseline.py
├── pyproject.toml
├── requirements.txt
└── README.md
```

**Note:** The NER and Presidio detectors, main pipeline, and risk engine are currently placeholders for future development.

## Installation & Setup

**Prerequisites**
- Git
- Python 3.13 (specified in `.python-version`)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

**Setup**

1. Clone the repository and navigate to the project directory.
2. Install the project dependencies:

   ```bash
   uv sync
   ```

3. Verify the setup by running the tests:

   ```bash
   uv run python -m pytest tests/ -v
   ```

## Usage

The Regex-based detection baseline is currently implemented and verified through automated tests.

To run the tests:

```bash
uv run python -m pytest tests/ -v
```

**TODO:** Add usage examples and execution instructions once the detection pipeline is integrated.

## Dataset

The project currently uses the `mabahboh/sitr-arabic-pii` dataset for initial exploration and baseline evaluation.

The final dataset selection and supported PII categories will be updated after defining the project scope.
