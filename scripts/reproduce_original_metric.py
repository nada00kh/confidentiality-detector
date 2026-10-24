"""Re-score an existing checkpoint with the ORIGINAL metric and with the corrected protocol,
so the change in numbers can be attributed step by step.

  python scripts/reproduce_original_metric.py --model-dir /content/ckpt/checkpoint-4352

Rows (all on the original validation split):
  A  token-level seqeval, -100 -> O in gold and prediction   (archive/04 compute_metrics)
  B  token-level seqeval, -100 positions dropped
  C  document-level character spans, v1 gold (non-targets ignored, no IPv4 remap)
  D  document-level character spans, v2 gold (non-targets scoreable, IP->IPV4, MIDDLENAME/MASKEDNUMBER ignored)
A should reproduce the reported 0.9925 F1 if this is the same checkpoint and data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import torch  # noqa: E402

from confidentiality_detector.alignment import training_features  # noqa: E402
from confidentiality_detector.detectors.transformer import TransformerDetector  # noqa: E402
from confidentiality_detector.documents import document_from_ai4privacy, load_documents, read_jsonl  # noqa: E402
from confidentiality_detector.labels import ID2LABEL, V1_ORIGINAL  # noqa: E402
from confidentiality_detector.metrics import evaluate, seqeval_token_metrics  # noqa: E402
from confidentiality_detector.runio import write_json  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--raw", type=Path, default=ROOT / "data/raw/english_pii_43k.jsonl")
    ap.add_argument("--manifests", type=Path, default=ROOT / "data/splits/original")
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval")
    ap.add_argument("--out", type=Path, default=ROOT / "reports/runs/original_metric_reproduction.json")
    args = ap.parse_args()

    det = TransformerDetector(args.model_dir, batch_size=64)
    tok, model, device = det.tokenizer, det.model, det.device

    val_ids = (args.manifests / "validation.ids").read_text().split()
    wanted = set(val_ids)
    raw = {str(r["id"]): r for r in read_jsonl(args.raw) if str(r["id"]) in wanted}
    v1_docs = [document_from_ai4privacy(raw[i], V1_ORIGINAL) for i in val_ids]

    # A/B: exactly the windows the original Trainer evaluated (verified identical in tests).
    windows = [f for d in v1_docs for f in training_features(tok, d, 512, 32)]
    label_rows, pred_rows = [], []
    with torch.inference_mode():
        for i in range(0, len(windows), 64):
            batch = windows[i:i + 64]
            width = max(len(w["input_ids"]) for w in batch)
            ids = torch.full((len(batch), width), tok.pad_token_id)
            mask = torch.zeros((len(batch), width), dtype=torch.long)
            for r, w in enumerate(batch):
                ids[r, :len(w["input_ids"])] = torch.tensor(w["input_ids"])
                mask[r, :len(w["input_ids"])] = 1
            pred = model(input_ids=ids.to(device), attention_mask=mask.to(device)).logits.argmax(-1).cpu()
            for r, w in enumerate(batch):
                label_rows.append(w["labels"])
                pred_rows.append(pred[r, :len(w["labels"])].tolist())
    a = seqeval_token_metrics(label_rows, pred_rows, ID2LABEL, ignored="as_O")
    b = seqeval_token_metrics(label_rows, pred_rows, ID2LABEL, ignored="drop")

    # C/D: document-level character-span evaluation with lenient decoding.
    v2_docs = load_documents(args.eval_dir / "validation.jsonl")
    preds = dict(zip([d.doc_id for d in v2_docs], det.detect_batch([d.text for d in v2_docs])))
    c = evaluate(v1_docs, preds)
    d = evaluate(v2_docs, preds)

    rows = {
        "A_seqeval_ignored_as_O": {k: a[k] for k in ("precision", "recall", "f1")},
        "B_seqeval_ignored_dropped": {k: b[k] for k in ("precision", "recall", "f1")},
        "C_charspan_v1_gold": {k: c["entity"]["micro"][k] for k in ("precision", "recall", "f1")},
        "D_charspan_v2_gold": {k: d["entity"]["micro"][k] for k in ("precision", "recall", "f1")},
    }
    out = {"model_dir": str(args.model_dir), "rows": rows,
           "D_fp_breakdown": d["entity"]["fp_breakdown"], "D_hard_negative_fp": d["entity"]["hard_negative_fp"],
           "D_per_class": d["entity"]["per_class"], "D_document": d["document"],
           "A_report": a["report"]}
    write_json(args.out, out)
    for k, v in rows.items():
        print(f"{k:28} P {v['precision']:.4f} R {v['recall']:.4f} F1 {v['f1']:.4f}")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
