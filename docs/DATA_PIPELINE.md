# Data pipeline

```
raw ai4privacy JSONL ──► schema check ──► annotation policy (v1/v2/v3) ──► Document (char spans: target / negative / ignore)
                                                                              │
original split manifests (record level, audited) ─────────────────────────────┤
round-2 generators (template families, family-level split, quality gates) ────┤
hand-written case files (dev_v1, challenge_v1 + overlay, challenge_v2) ───────┤
                                                                              ▼
                        tokenisation (fast tokenizer, offsets) ─► BIO alignment ─► sliding windows ─► training
                        evaluation: document-level character spans (never windows)
```

All code paths share one implementation per step:
* `documents.py`: schema;
* `labels.py`: policy;
* `alignment.py`: tokenisation, alignment and windows;
* `decoding.py`: tokens → spans;
* `metrics.py`.

## 1. Sources

| Source | What | Role |
|---|---|---|
| `data/raw/english_pii_43k.jsonl` | English slice of `ai4privacy/pii-masking-200k` (43,501 synthetic records, 56 source labels; sha256 in `data/eval*/manifest.json`) | training / validation / synthetic test |
| `data/synth/round2/` | round-2 generated documents: A = hard negatives, B = difficult positives (`synth.py`, `scripts/build_synth_round2.py`, seed 2026, generator `round2-v1`) | training (`*_train`), held-out-family evaluation (`*_heldout`) |
| `data/dev/dev_v1.txt` | 135 hand-written cases (75 ALLOW / 56 BLOCK / 4 AMBIGUOUS), frozen sha256 `3ea038b1…` before the round-2 generators existed | development: model selection and operating points |
| `data/challenge/challenge_v1.txt` (+ overlay) | 154 hand-written cases, frozen `c19cd914…`; overlay applies the final person-name policy | regression and debugging only (its failures were studied) |
| `challenge_v2` (not in the repository) | independently written, hidden | final benchmark, via `scripts/challenge_v2.py` |

No real user data or real secrets are used anywhere:
* phone numbers use reserved 555-01xx ranges;
* cards are Luhn-valid generated numbers or public test numbers;
* IBANs are generated with valid checksums or are published specimens;
* names are invented, except deliberately included public figures.

## 2. Schema and annotation policy

`Document(doc_id, text, spans, ignore_spans, negative_spans, meta)`, serialised as JSONL with `[start, end, label]` triples. Every document is validated on load: spans must lie inside the text and target spans must not overlap. Converting ai4privacy records also checks that each `value` equals the text slice.

The source labels are mapped by an explicit, versioned **label policy** (`labels.LabelPolicy`):

| Policy | Rule | Used by |
|---|---|---|
| v1_original | every non-target entity is ignored (-100) | the original notebooks and checkpoint-4352; reproduced exactly by `tests/test_alignment.py` |
| v2 | out-of-scope entities → `O` (hard negatives); `IP` with an IPv4 value → IPV4; MIDDLENAME and MASKEDNUMBER ignored | round 1 (E1, E2), `data/eval/` |
| **v3** (current) | v2 + CREDITCARDCVV needs contextual evidence, otherwise ignored (15.8% of training CVVs) | round 2, `data/eval_v3/` |

The rules are documented in `docs/ANNOTATION_GUIDELINES.md`; their rationale and measurements are in `reports/INVESTIGATION.md` §2 and `reports/ROUND2_PLAN.md`.

## 3. Quality checks

* **Dataset audit** (`scripts/audit_dataset.py` → `reports/dataset_audit.json`): cross-split exact and normalised duplicates, TF-IDF near-duplicate templates, value and context reuse, format realism (Luhn, mod-97, digit counts), and how much each policy ignores.
* **Generated data** (`scripts/build_synth_round2.py`) is a hard gate:
  * every document must pass `synth.validate_synthetic`: scope, CVV evidence, no unannotated person names;
  * exact duplicates are removed;
  * the **contamination guard** drops documents with TF-IDF cosine ≥ 0.5 to any `dev_v1` or `challenge_v1` case, and documents reusing one of their target values;
  * the name pool excludes every name in `dev_v1`, `challenge_v1` and format family B.
  * Result: maximum similarity to dev/challenge is 0.20, and 0 documents were dropped for similarity. The first template draft *was* contaminated; it paraphrased dev cases and was rewritten before generation (`reports/ROUND2_PLAN.md`).
* **Training time** (`scripts/train.py`): extra training files must match the sha256 in their manifest, and every extra document is re-checked for scope and CVV evidence before any GPU time is spent.
* **Case files** (`challenge.parse_case`, `scripts/challenge_v2.py validate`) check markup, the document decision against the spans, scope, CVV evidence (warning) and checksums (warning).

## 4. Splitting

* **ai4privacy.** The original record-level 80/10/10 split (seed 42) is kept, as ID manifests in `data/splits/original/`. Keeping it is what makes the existing checkpoint's test split usable and keeps every round comparable.
  * Group-level re-splitting was evaluated and found unnecessary: there are zero cross-split exact or template duplicates, and fewer than 1% of validation/test documents reach a near-duplicate similarity of 0.5 to train.
  * Windows are built *after* splitting, from documents of one split only.
* **Generated data.** The split is by **template family** (value group × document frame). In every value group with two or more families, one whole family is held out (`synth.split_families`): 11 of 48 families, about 25% of generated documents.
  * Held-out families never enter training; they form `synth_A_heldout` / `synth_B_heldout`.
  * Their median maximum similarity to training documents is 0.05–0.07.
* **Hand-written sets** are never trained on. `dev_v1` is used for selection only. `challenge_v1` is regression-only. `challenge_v2` is final and evaluated through a sealed, ledgered interface.

## 5. Tokenisation, BIO alignment and windows

* **Tokenisation.** A fast tokenizer with offset mapping, on the original text, with no normalisation, so offsets always refer to the input characters.
* **BIO alignment** (`alignment.token_label_ids`), per subword token:
  * no annotation → `O`;
  * inside a target span → `B-`/`I-<label>`;
  * inside a negative span → `O`;
  * inside an ignore span, straddling a span boundary, or overlapping two annotations → ignored (-100);
  * a target entity with any ignored token is ignored entirely, so no half-labelled entity is trained or scored.
* **Training windows** (`alignment.plan_windows`): at most 510 subword tokens per window, plus [CLS]/[SEP]. Each window re-reads up to 32 tokens of left context, labelled -100, so every token is supervised exactly once. Windows never end inside an entity.
* **Inference windows.** Settings come from the `inference` section of `configs/inference/policy.json` (default 512 tokens, 64 overlap, `"first"` stitching, as evaluated in Rounds 1 and 2).
  * Every token is predicted by exactly one window, and predictions are stitched onto the full document *before* decoding, so an entity crossing a window boundary is one span.
  * With `"first"` stitching, the last tokens before a cut have no right context. This is measured to concentrate long-document errors (`reports/ROUND2_REPORT.md` §3).
  * `"centered"` stitching moves the cut to the middle of the overlap, so every token near a cut has ≥ 32 tokens of context on both sides. It is adopted only through the window study (`docs/METHODOLOGY.md` §7).
  * Every model input is checked to be ≤ `max_length`, and the tokenizer's whole-document length warning is silenced because the full sequence never reaches the model.
  * Tested in `tests/test_alignment.py` and `tests/test_pipeline.py` (1,000+-token document, forward hook on model inputs).

## 6. Versioning and reproducibility

| Artefact | Identity recorded in |
|---|---|
| raw data | sha256 in every eval manifest and in `training_summary.json` |
| split | `data/splits/original/*.ids` (sha256 in `training_summary.json`) |
| eval sets | `data/eval/manifest.json` (round 1, v2) and `data/eval_v3/manifest.json` (round 2, v3): policy, seed, per-file sha256 |
| generated data | `data/synth/round2/manifest.json`: generator version, seed, family split, gate statistics, sha256 |
| hand-written sets | `.sha256` files next to them; the overlay pins the sha256 of the file it modifies |
| training run | `training_summary.json`: full config, environment, data versions, tokenizer, per-epoch history, reload check |
| Colab bundle | `BUNDLE_INFO.json`: bundle version and per-file sha256, verified on Colab before anything runs |
| predictions | `run_info.json` per prediction run: sha256 of each evaluation file predicted. `evaluate.py` and every analysis script **refuse** predictions made on a different file version (`runio.check_provenance`). Reuse across versions only via `scripts/retarget_predictions.py`, which requires byte-identical texts |

Rebuild everything from the raw file:

```bash
python scripts/build_eval_sets.py --policy v2 --out data/eval        # round-1 suite (frozen copy already in data/eval)
python scripts/build_synth_round2.py                                 # round-2 generated data (deterministic)
python scripts/build_eval_sets.py --policy v3 --out data/eval_v3     # round-2 suite (includes dev_v1, overlay, held-out families)
python scripts/audit_dataset.py
python -m pytest -q
```

Rebuilding v2 reproduces the Round 1 files byte for byte, with one exception. The tag of the two ambiguous `challenge_v1` cases changed from `allow` to `ambiguous`, which corrects a tagging bug. Those cases were already excluded from document metrics, so no Round 1 number changes.

**What is in version control.** Git holds the sources and identities: the hand-written sets and overlays (`data/dev/`, `data/challenge/`), the split ids, every manifest, and the four small `data/eval_v3/` files built from the hand-written sets (`dev_v1`, `challenge_v1*`). Two kinds of file stay out of Git and are regenerated with the commands above:
* files derived from the third-party raw file, whose licence is not recorded in this repository;
* bulk generated data.

On 2026-10-24, regenerating both on CPU in about 30 s reproduced all 19 files in `data/eval_v3/` and `data/synth/round2/` byte for byte, matching the manifest hashes. The raw file itself (`data/raw/english_pii_43k.jsonl`, sha256 `1a7aac12…`) was downloaded from the Hugging Face Hub at revision `7c22e6816b8f…`.
