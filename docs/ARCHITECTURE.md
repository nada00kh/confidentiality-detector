# Architecture

## 1. Responsibilities and modules

| Responsibility | Modules | Depends on |
|---|---|---|
| **Scope and annotation policy** | `labels.py` (13 targets, BIO mapping, label policies v1–v3, CVV evidence) | — |
| **Data model** | `documents.py` (Document/Span, JSONL, ai4privacy conversion) | labels |
| **Data engineering** | `perturb.py` (format families A/B), `synth.py` (round-2 generators and validation), `challenge.py` (case-file parser, policy overlay); `scripts/build_eval_sets.py`, `build_synth_round2.py`, `audit_dataset.py` | documents, labels |
| **Tokenisation and alignment** (shared by training and inference) | `alignment.py` (offsets, BIO, windows), `decoding.py` (token predictions → spans, thresholds) | labels |
| **Training** | `scripts/train.py`; Colab: `scripts/make_colab_bundle.py`, `colab_runner.py`, `colab_round2.py` (`colab_round1.py` frozen for Round 1), notebooks in `notebooks/colab/` | alignment, metrics, detectors.transformer |
| **Evaluation and selection** | `metrics.py`, `runio.py`; `scripts/predict.py`, `evaluate.py` (model/hybrid level), `evaluate_system.py` (full BLOCK/ALLOW system), `verify_checkpoint.py`, `challenge_v2.py`, `contamination.py`; one-off studies behind the reports in `scripts/analysis/` | documents, decoding, detectors |
| **Detection** | `detectors/transformer.py` (windowed model inference), `detectors/rules.py` (deterministic, rules v3), `detectors/hybrid.py` (`merge`: span reconciliation), `detectors/presidio_detector.py` (baseline only) | alignment, decoding, labels |
| **Security policy** | `policy.py` (modes, BLOCK/ALLOW, fail-closed, safe explanations); `configs/inference/policy.json` | labels |
| **Inference pipeline** | `pipeline.py` (`ConfidentialityDetector`), `__main__.py` (CLI) | detectors, decoding, policy |

Import isolation is tested:
* `policy.py` and `pipeline.py` do not import torch at module load.
* `detectors.transformer` and `detectors.hybrid` do not need `phonenumbers` or Presidio.

## 2. From prompt to decision

```
text (str)
  │  input validation: non-str → TypeError; empty → ALLOW (EMPTY_INPUT); > max_chars → BLOCK (INPUT_TOO_LARGE)
  ▼
TransformerDetector.token_predictions                         RuleDetector.detect
  │ fast tokenizer, offsets on the ORIGINAL text                │ regex + validators + context cues on the original text
  │ windows ≤ 510 tokens, 64 overlap (policy.json `inference`)  │ (Luhn, IBAN mod-97, IPv4 octets, phone parsing,
  │ each token predicted once; probabilities stitched           │  CVV evidence, JSON/YAML/SQL/CLI credential patterns)
  ▼                                                             ▼
decode(threshold of the security mode) ──► model spans       rule spans (overlaps resolved by priority)
                    └──────────────── reconcile (hybrid.merge) ───────────────┘
                         • for EMAIL, IPV4, IBAN, CREDITCARDNUMBER, SSN the rule span wins on overlap
                           (validator-exact boundaries); otherwise the model span wins
                         • non-overlapping spans from both are kept; the result has no overlaps
                         • every finding keeps (start, end, label, source, score)
  ▼
evaluate_policy(findings, PolicyConfig, mode)
  │  BLOCK if any finding label ∈ blocking_labels (all 13) else ALLOW
  │  any exception above → BLOCK (INSPECTION_ERROR), logged without text
  ▼
Decision{decision, reason, mode, categories, findings, policy_version}
  .explanation() / .to_dict()  → categories, counts, positions; never values
```

Properties and where they are tested:

| Property | Test |
|---|---|
| offsets refer to the input characters | `tests/test_pipeline.py::test_rules_add_structured_findings_with_source` |
| long inputs: entity past the first window found, no overlapping findings | `test_end_to_end_with_saved_checkpoint_long_document` (real checkpoint format, 6,000+ characters) |
| fail closed | `test_fail_closed_on_error_oversize_and_empty` |
| no values in outputs or logs | `test_outputs_and_logs_never_contain_values` |
| modes change sensitivity only | `test_block_allow_and_mode_thresholds` |
| checkpoint integrity on load | `TransformerDetector` raises on missing/mismatched keys and on a label-mapping mismatch |

Model predictions (`findings` with `source` and `score`) are kept distinct from the policy outcome (`decision`, `reason`). An audit can always see *why* a prompt was blocked without seeing *what* was in it.

## 3. Using it

```python
from confidentiality_detector.pipeline import ConfidentialityDetector
detector = ConfidentialityDetector.load("checkpoints/r2_e3b_positive", "configs/inference/policy.json")
decision = detector.inspect(prompt_text)              # default mode: strict
decision.to_dict()                                    # {"decision": "BLOCK", "categories": [...], "findings": [...], ...}
```

```bash
confidentiality-detector --model-dir checkpoints/r2_e3b_positive --file prompt.txt   # or python -m confidentiality_detector; exit 0 = ALLOW, 10 = BLOCK, 2 = error
```

**Resources** (round-1 measurements, laptop CPU, mBERT-base):
* about 37 ms median per prompt (p95 219 ms);
* 0.6–2.9 s for 600–1,000-token documents;
* rules take under 1 ms;
* the model is 709 MB on disk.

Inference needs no training code, GPU or network: weights are loaded with `local_files_only=True`.

## 4. Configuration

* `configs/inference/policy.json` is the deployed system's whole configuration, not only the security policy:
  * blocking labels (must be within the 13);
  * security modes (token threshold, rules on/off, evidence);
  * `max_chars`, `on_error`, `on_oversize` and the policy version;
  * the transformer's `inference` windows (512 / 64 / first, `docs/METHODOLOGY.md` §7).

  Unknown settings are rejected, so a misspelt or retired key cannot be silently ignored. `scripts/challenge_v2.py freeze` fingerprints the file (sha256) together with the model weights and the rules version.
* `configs/experiments/*.json`: training runs. Unspecified fields take `scripts/train.py` `DEFAULTS`, and the merged config is stored with every checkpoint.
