"""Reproducible dataset audit (leakage, duplication, value/format realism, label policy impact).

  python scripts/audit_dataset.py   ->  reports/evidence/dataset_audit.json
Values are never written out; only counts, rates, and character-class shapes.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from confidentiality_detector.alignment import encode_text, token_label_ids  # noqa: E402
from confidentiality_detector.detectors.rules import iban_valid, luhn_valid  # noqa: E402
from confidentiality_detector.documents import document_from_ai4privacy, read_jsonl  # noqa: E402
from confidentiality_detector.labels import IGNORE_INDEX, TARGET_LABELS, V1_ORIGINAL, V2  # noqa: E402
from confidentiality_detector.metrics import mask_value  # noqa: E402


def shape(value: str) -> str:
    return re.sub(r"(.)\1{2,}", r"\1\1+", mask_value(value))


def main() -> None:
    raw = {str(r["id"]): r for r in read_jsonl(ROOT / "data/raw/english_pii_43k.jsonl")}
    ids = {n: (ROOT / f"data/splits/original/{n}.ids").read_text().split() for n in ("train", "validation", "test")}
    split = {n: [raw[i] for i in v] for n, v in ids.items()}
    out: dict = {"n_records": {n: len(v) for n, v in split.items()}}

    # Exact / normalised duplicates across splits.
    norm = lambda t: " ".join(t.lower().split())  # noqa: E731
    texts = {n: {norm(r["source_text"]) for r in v} for n, v in split.items()}
    templates = {n: {norm(r["target_text"]) for r in v} for n, v in split.items()}
    out["cross_split_duplicates"] = {
        f"{a}-{b}": {"normalised_text": len(texts[a] & texts[b]), "placeholder_template": len(templates[a] & templates[b])}
        for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))
    }

    # Near-duplicate templates (TF-IDF 1-3 grams on placeholder text).
    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(ngram_range=(1, 3), sublinear_tf=True)
    xtr = vec.fit_transform(r["target_text"] for r in split["train"])
    near = {}
    for n in ("validation", "test"):
        x = vec.transform(r["target_text"] for r in split[n])
        m = np.concatenate([(x[i:i + 512] @ xtr.T).max(axis=1).toarray().ravel() for i in range(0, x.shape[0], 512)])
        near[n] = {"median_max_cosine": float(np.median(m)),
                   **{f"share_ge_{t}": float((m >= t).mean()) for t in (0.5, 0.7, 0.8, 0.9)}}
    out["near_duplicate_templates_vs_train"] = near

    # Value and context reuse train -> validation.
    train_vals, train_ctx = defaultdict(set), defaultdict(set)
    ctx = lambda r, a: " ".join(r["source_text"][:a["start"]].lower().split()[-2:])  # noqa: E731
    for r in split["train"]:
        for a in r["privacy_mask"]:
            train_vals[a["label"]].add(a["value"])
            train_ctx[a["label"]].add(ctx(r, a))
    reuse = {}
    for label in TARGET_LABELS:
        anns = [(r, a) for r in split["validation"] for a in r["privacy_mask"] if a["label"] == label]
        reuse[label] = {"n": len(anns),
                        "value_seen_in_train": sum(a["value"] in train_vals[label] for _, a in anns) / len(anns),
                        "left2_context_seen_in_train": sum(ctx(r, a) in train_ctx[label] for r, a in anns) / len(anns)}
    out["validation_reuse_from_train"] = reuse

    # Format realism of structured values (all splits).
    vals = defaultdict(list)
    for r in raw.values():
        for a in r["privacy_mask"]:
            vals[a["label"]].append(a["value"])
    out["format"] = {
        label: {"n": len(v), "distinct_shapes": len({shape(x) for x in v}),
                "top_shapes": Counter(shape(x) for x in v).most_common(5)}
        for label in sorted(set(TARGET_LABELS) | {"IP", "MASKEDNUMBER", "PIN", "PHONEIMEI"})
        for v in [vals[label]]
    }
    out["validator_pass_rates"] = {
        "CREDITCARDNUMBER_luhn": sum(luhn_valid(re.sub(r"\D", "", x)) for x in vals["CREDITCARDNUMBER"]) / len(vals["CREDITCARDNUMBER"]),
        "CREDITCARDNUMBER_with_separators": sum(bool(re.search(r"\D", x)) for x in vals["CREDITCARDNUMBER"]) / len(vals["CREDITCARDNUMBER"]),
        "IBAN_mod97": sum(iban_valid(x) for x in vals["IBAN"]) / len(vals["IBAN"]),
        "SSN_9_digits": sum(len(re.sub(r"\D", "", x)) == 9 for x in vals["SSN"]) / len(vals["SSN"]),
        "IP_label_with_ipv4_value": sum(bool(re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", x)) for x in vals["IP"]) / len(vals["IP"]),
        "MASKEDNUMBER_16_digits": sum(bool(re.fullmatch(r"\d{16}", x)) for x in vals["MASKEDNUMBER"]) / len(vals["MASKEDNUMBER"]),
    }

    # Label-policy impact on supervision and on what the metric can see (validation).
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained("google-bert/bert-base-multilingual-cased")
    policy_stats = {}
    for policy in (V1_ORIGINAL, V2):
        n_tok = n_ign = 0
        docs_no_target = 0
        for r in split["validation"]:
            d = document_from_ai4privacy(r, policy)
            labels = token_label_ids(encode_text(tok, d.text).offsets, d)
            n_tok += len(labels)
            n_ign += sum(x == IGNORE_INDEX for x in labels)
            docs_no_target += not d.spans
        policy_stats[policy.name] = {"ignored_token_share": n_ign / n_tok, "docs_without_target": docs_no_target}
    out["label_policy_validation"] = policy_stats
    out["validation_entity_counts"] = Counter(
        "target" if a["label"] in TARGET_LABELS else "non_target" for r in split["validation"] for a in r["privacy_mask"])

    path = ROOT / "reports/evidence/dataset_audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("cross_split_duplicates", "near_duplicate_templates_vs_train",
                                          "validator_pass_rates", "label_policy_validation")}, indent=1))


if __name__ == "__main__":
    main()
