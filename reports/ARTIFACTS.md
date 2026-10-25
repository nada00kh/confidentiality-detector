# Artifacts outside Git

Large or irreplaceable files are kept out of the repository. This page records where each one is and how to recognise it. sha256 values are given in full where they identify a file; Drive paths are relative to `MyDrive/confidentiality_detector/` in the project owner's Google Drive (the Colab workspace).

The selected checkpoint is shared with team members through a private Google Drive folder whose link is not recorded here. How to install and verify it on another computer: `docs/INTEGRATION.md` §1.2–1.4.

## Model checkpoints

| Artifact | Where | Identity |
|---|---|---|
| **R3 `r2_e3b_positive` (selected)** | local `checkpoints/r2_e3b_positive/` (git-ignored); Drive `round2/checkpoints/r2_e3b_positive/`. The Drive download is `Downloads/r2_e3b_positive-20261024T130931Z-1-001.zip` (659,035,598 bytes, sha256 `b63aadaa452a5ecee8b2de735091314bffcc0e9c70e68fe01e68361867fef2f0`) | `model.safetensors`: 709,157,780 bytes, sha256 `dc0fdca52f9e144b4017cb8eb37d8cef0d366b5b9619c519a782102ef32850c6`. `config.json` and `training_summary.json` are identical to `results/round2/checkpoint_meta/r2_e3b_positive/`. Reproduces every archived Round 2 prediction (`reports/evidence/checkpoint_verification_r2_e3b_positive.json`) |
| R1, R2, R4 (`r2_e2_v3`, `r2_e3a_hardneg`, `r2_e4_combined`) | Drive `round2/checkpoints/<run>/` | metadata in `results/round2/checkpoint_meta/<run>/` |
| E2 `e2_mbert_v2_fmtA` (Round 1 winner, Round 2 baseline R0) | Drive `round1_rerun/checkpoints/e2_mbert_v2_fmtA` | metadata in `results/round1/checkpoint_meta/` |
| `checkpoint-4352` (original notebook 04 model) | Drive `mbert_checkpoints/` | Round 1 baseline `mbert_original` |

## Colab result archives (not reproducible without GPU retraining)

| Archive | Extracted to (git-ignored) | Identity |
|---|---|---|
| `Downloads/round1_results.zip` (also on Drive) | `results/round1/` (81.9 MB) | 13,144,512 bytes, sha256 `1b9b11df215fb6e2ebbb2fd8dee59c08985e1c05ff26901da47700c5e5005d4a`; per-file hashes in `RESULTS_MANIFEST.json` |
| `Downloads/round2_results.zip` (also on Drive; `round2_results (1).zip` is a byte-identical second download) | `results/round2/` (145.0 MB) | 22,138,962 bytes, sha256 `85e99bf901327a5fe1cc3820557e050bdbf39dc2d857727296dafcadda2f7b24`; verified by `scripts/analysis/verify_round2.py` |

`results/round2_derived/` holds predictions retargeted to `challenge_v1_final` (byte-identical texts). It is regenerable with `scripts/analysis/retarget_predictions.py`.

## Colab bundles (the exact code that ran)

| Bundle | Identity |
|---|---|
| `dist/colab_bundle_round1-r2.zip` (Round 1 rerun) | 17,576,408 bytes, sha256 `1499e7d463e54a14a489de81c17eec98f445070382b71f012ccd6c575698b156` |
| `dist/colab_bundle_round2.zip` (`round2-r1`) | 17,917,404 bytes, sha256 `505e76c5742701bac4cf829498e18ef4a6c8c114e27d41d15aa39243a674a6c2` |

`dist/colab_bundle.zip` was deleted on 2026-10-24: it was byte-identical to `colab_bundle_round1-r2.zip` (same sha256).

## Local, regenerable (git-ignored)

* `predictions/`: Round 1 local predictions (Presidio, rules v1/v2).
* `predictions_v3/`:
  * rules v2/v3 on the v3 sets;
  * Round 1 E2 retargeted to v3;
  * `cpu_local/`: R3 on `validation_long`, predicted on CPU, which has no Colab prediction.
* `reports/runs/`: Round 1 per-run metrics.

## Original notebook outputs (`data/processed/`, git-ignored)

* `mbert_splits/` and `mbert_tokenized/` are kept. `tests/test_alignment.py` uses them.
* On 2026-10-24 the following were deleted:
  * six `datasets` cache files (`mbert_splits/*/cache-*.arrow`, 57 MB), which are regenerated on demand;
  * two zip copies made for upload to Drive, after a member-by-member comparison with the folders:
    * `mbert_splits.zip` (20,328,699 bytes, sha256 `156d6712674edba764e66b475af1d42c946d03ff8b3f4d22e695f2fb490bb372`): all 10 members byte-identical to the folder.
    * `mbert_tokenized.zip` (4,580,084 bytes, sha256 `813c3f819b2ac2d53c02da5881314ef9d463cd3394e54bbea9f556d202a928b8`): the data files are byte-identical. Only the three `state.json` files differ, in the `datasets` `_fingerprint` field: the zip recorded test `b1d9a2077d358d7c`, train `dc173d66894f8965` and validation `ee08f2ddd74ffc0c`, while the folder records `fea45858e304556e`, `e45f9a2efbe1efaa` and `2f34e01f5ceb5115`. That is, the zip came from a different run of notebook 03 with identical output. The Drive copy used by notebook 04 is unaffected.

## Raw data

`data/raw/english_pii_43k.jsonl`: 43,501 English records of `ai4privacy/pii-masking-200k`, sha256 `1a7aac12051b87390a18fe8ece2010cfa8c1631e0b69c46e6ed5a995b374a7f8`. Provenance: `docs/DATA_PIPELINE.md` §0.
