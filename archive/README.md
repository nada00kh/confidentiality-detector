# Archive: the project's original experiments

These files are the project's first exploration and baseline. They are kept **unchanged** as historical evidence, with their cells and outputs exactly as they were run. They were moved here from `notebooks/` with `git mv` on 2026-10-24, so `git log --follow` shows their history. They are **not** part of the current pipeline. The authoritative implementation is the `confidentiality_detector` package plus `scripts/` (see the main README and `docs/DATA_PIPELINE.md`).

| File | What it did | Status today |
|---|---|---|
| `02_scoped_data_EDA.ipynb` | **Earliest exploration, from the project's original Arabic direction.** EDA of the Arabic SITR PII dataset (`mabahboh/sitr-arabic-pii`) against an older 11-category scope (`national_id`, `iqama`, `api_key`, …). | Historical only. That direction was abandoned, and none of its data or categories is used. |
| `scope_original.md` | The original scope document (Arabic, regex-based), already marked superseded. | Historical only. The current scope is `docs/POLICY.md` (summary in `../scope.md`). |
| `02_2scoped_data_EDA.ipynb` | EDA of `ai4privacy/pii-masking-200k`. It filters `language == "en"` (43,501 of 209,261 records) and measures coverage of the 13 target labels, offset consistency, quality and duplicates. It also explores mBERT tokenisation, BIO labelling and chunking, including entities cut by chunk boundaries. | Establishes the data source. The English filter is the origin of `data/raw/english_pii_43k.jsonl`. The descriptive statistics remain valid. |
| `02_mbert_dataset_splitting.ipynb` | 80/10/10 split with template-leakage removal, giving 34,802 / 4,350 / 4,349 documents. Writes `data/processed/mbert_splits`. | **Still authoritative.** Its ids are frozen in `data/splits/original/*.ids`, and every Round 1 and Round 2 model was trained and evaluated on them. |
| `03_mbert_tokenization_and_alignment.ipynb` | Offset and BIO validation; 512-token windows with 32-token overlap. Writes `data/processed/mbert_tokenized`. | **The alignment was correct.** `alignment.training_features` reproduces its output exactly (`tests/test_alignment.py`). It used label policy v1, which sets out-of-scope entities to -100. |
| `04_mbert_finetuning.ipynb` | Colab fine-tuning of mBERT with the HF Trainer: lr 2e-5, 2 epochs, batch 4 × 4 gradient accumulation (effective 16), weight decay 0.01, fp16, seed 42, best epoch by seqeval F1. It produced `checkpoint-4352`, with a reported validation F1 of 0.9925. | Learning rate, epochs, effective batch, weight decay and seed were kept for every later run, which added a 10% warm-up. The 0.9925 was a metric artefact: out-of-scope entities were invisible to token-level seqeval. On document-level character spans the same model scores 0.643 (`reports/history/ROUND1_REPORT.md`). |

## What was later corrected, and what was not

* **Corrected:**
  * the **label policy**: out-of-scope entities are now trained and scored as `O` (policy v2), and a CVV needs contextual evidence (v3);
  * the **evaluation**: document-level character spans replaced token-level scores on windows.
* **Not changed:** the source data, the English filter, the split, and the tokenisation and alignment mechanics.

## Running them today

* The relative paths (`../data/raw/...`, `../data/processed/...`) still resolve from this folder.
* **Overwrite risk:** notebooks `02_mbert_dataset_splitting` and `03_…` **write** to `data/processed/`. Re-running them would overwrite the preserved outputs that `tests/test_alignment.py` checks. Run them on a copy if needed.
* `02_2scoped_data_EDA` and `02_scoped_data_EDA` download their datasets from the Hugging Face Hub.
* `04_mbert_finetuning` expects Google Colab with Drive paths and a GPU.
* Their Python dependencies (`pandas`, `ipykernel`) are in the optional dependency group: `uv sync --group notebooks`.
