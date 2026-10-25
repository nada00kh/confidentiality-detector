"""Invariants of the round-2 data generators and of the generated files on disk."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pytest

from confidentiality_detector.documents import load_documents
from confidentiality_detector.labels import TARGET_SET, cvv_has_evidence
from confidentiality_detector.synth import (
    FAMILIES, FIRST_NAMES_C, LAST_NAMES_C, family_kind, generate, split_families, validate_synthetic,
)

ROOT = Path(__file__).resolve().parents[1]
SYNTH = ROOT / "data/synth/round2"
NAMES = (FIRST_NAMES_C, LAST_NAMES_C)


def test_family_split_holds_out_whole_families_per_group():
    split = split_families()
    assert split == split_families()  # deterministic
    groups = defaultdict(list)
    for fid, part in split.items():
        groups[(family_kind(fid), fid.split(".")[1])].append(part)
    for parts in groups.values():
        assert parts.count("heldout") == (1 if len(parts) >= 2 else 0)


def test_generation_is_deterministic_and_policy_valid():
    a, b = generate(4, 11, NAMES), generate(4, 11, NAMES)
    assert {k: [d.text for d in v] for k, v in a.items()} == {k: [d.text for d in v] for k, v in b.items()}
    for docs in a.values():
        for d in docs:
            assert validate_synthetic(d, NAMES) == [], d.doc_id
            for s in d.spans:
                assert s.label in TARGET_SET
                if s.label == "CREDITCARDCVV":
                    cards = [(c.start, c.end) for c in d.spans if c.label == "CREDITCARDNUMBER"]
                    assert cvv_has_evidence(d.text, s.start, s.end, cards)
    assert all(d.meta["split"] == "train" for k in ("A_train", "B_train") for d in a[k])
    assert all(d.meta["split"] == "heldout" for k in ("A_heldout", "B_heldout") for d in a[k])


def test_every_family_template_renders():
    assert len(FAMILIES) >= 40 and sum(len(t) for t in FAMILIES.values()) >= 120


# The manifest is in Git, the generated files are not (python scripts/build_synth_round2.py).
@pytest.mark.skipif(not (SYNTH / "A_train.jsonl").exists(), reason="round-2 data not built")
def test_built_files_match_manifest_and_never_mix_heldout_families():
    manifest = json.loads((SYNTH / "manifest.json").read_text(encoding="utf-8"))
    heldout = {f for f, part in manifest["family_split"].items() if part == "heldout"}
    for bucket, meta in manifest["files"].items():
        path = SYNTH / f"{bucket}.jsonl"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == meta["sha256"]
        families = {d.meta["family"] for d in load_documents(path)}
        if bucket.endswith("_train"):
            assert not families & heldout, bucket
        else:
            assert families <= heldout, bucket
