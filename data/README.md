# Data

The full lineage (source, policies, splits, generated data, and which run used what) is in [`docs/DATA_PIPELINE.md`](../docs/DATA_PIPELINE.md) §0. No real user data and no real secrets are used anywhere: every value is synthetic, a public test value, or invented for the hand-written sets.

| Folder | Contents | In Git? | Produced by |
|---|---|---|---|
| `raw/` | `english_pii_43k.jsonl`: the 43,501 English records of `ai4privacy/pii-masking-200k`, with the source's own columns (sha256 `1a7aac12…`). `.cache/` holds the Hub download metadata (revision `7c22e681…`). | no (third-party data; check the dataset licence before redistributing anything derived from it) | download (see `archive/02_2scoped_data_EDA.ipynb` for the English filter) |
| `splits/original/` | **The authoritative split**: 34,802 / 4,350 / 4,349 record ids | yes | exported once from the original splitting notebook's output |
| `dev/` | `dev_v1`: 135 hand-written development cases, frozen (sha256 file alongside) | yes | hand-written |
| `challenge/` | `challenge_v1`: 154 hand-written cases, frozen, plus two policy overlays and their README | yes | hand-written |
| `eval_v3/` | **Current evaluation suite** (label policy v3), with `manifest.json` (per-file sha256) and `manifest_round2.json` (as Round 2 evaluated it) | manifests and the four files built from the hand-written sets | `scripts/build_eval_sets.py --policy v3 --out data/eval_v3` |
| `synth/round2/` | Round 2 generated documents: `A_*` hard negatives, `B_*` difficult positives, `manifest.json` | manifest only | `scripts/build_synth_round2.py` |
| `eval/` | Round 1 evaluation suite (label policy v2), historical | manifest only | `scripts/build_eval_sets.py --policy v2 --out data/eval` |
| `processed/` | The original notebooks' outputs (`mbert_splits`, `mbert_tokenized`, label policy v1). Historical, but `tests/test_alignment.py` uses them to prove that the current alignment reproduces them | no | `archive/02_mbert_dataset_splitting.ipynb`, `archive/03_…` |

`challenge_v2/` (the independent final benchmark) is never stored here by developers. It is git-ignored and handled only through `scripts/challenge_v2.py`.

## Rebuild

From the raw file, the split ids and the hand-written sources:

```bash
python scripts/build_synth_round2.py                                  # data/synth/round2
python scripts/build_eval_sets.py --policy v3 --out data/eval_v3      # data/eval_v3 (uses data/synth/round2)
```

Both scripts are deterministic. On 2026-10-24, a rebuild reproduced all 19 files in these two folders byte for byte, matching the manifest hashes. `.gitattributes` keeps `data/` byte-exact (`-text`), because the hashes are recorded in manifests and prediction run files.
