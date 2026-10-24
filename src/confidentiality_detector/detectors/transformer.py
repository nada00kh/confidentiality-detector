"""Token-classification detector with document-level sliding-window inference.

Every token is predicted exactly once (by the window that owns it, with up to `overlap`
tokens of left context), predictions are stitched back onto the full document, and only
then decoded into character spans -- so entities cut by a window boundary survive and no
entity is counted twice.
"""

from __future__ import annotations

from pathlib import Path

import torch

from ..alignment import STITCHING, encode_text, inference_windows, wrap_window
from ..decoding import TokenPred, decode
from ..documents import Span
from ..labels import validate_label_mapping


class TransformerDetector:
    name = "transformer"

    def __init__(
        self,
        model_dir: str | Path,
        device: str | None = None,
        max_length: int = 512,
        overlap: int = 64,
        batch_size: int = 32,
        threshold: float | None = None,
        stitching: str = "first",
    ):
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        if not self.tokenizer.is_fast:
            raise ValueError("A fast tokenizer is required for offset mapping")
        self.model, info = AutoModelForTokenClassification.from_pretrained(
            str(model_dir), local_files_only=True, output_loading_info=True
        )
        missing = set(info.get("missing_keys", []))
        mismatched = info.get("mismatched_keys", [])
        if missing or mismatched:
            raise RuntimeError(f"Checkpoint did not load cleanly: missing={sorted(missing)[:10]} mismatched={mismatched[:10]}")
        self._setup(device, max_length, overlap, batch_size, threshold, stitching)

    @classmethod
    def from_model(cls, model, tokenizer, device=None, max_length=512, overlap=64, batch_size=32, threshold=None,
                   stitching="first"):
        """Wrap an in-memory model (used for per-epoch validation during training)."""
        self = cls.__new__(cls)
        self.model, self.tokenizer = model, tokenizer
        self._setup(device, max_length, overlap, batch_size, threshold, stitching)
        return self

    def _setup(self, device, max_length, overlap, batch_size, threshold, stitching="first"):
        validate_label_mapping(self.model.config.id2label)
        limit = getattr(self.model.config, "max_position_embeddings", None)
        if limit is not None and max_length > limit:
            raise ValueError(f"max_length={max_length} exceeds the model's {limit} positions")
        if stitching not in STITCHING:
            raise ValueError(f"stitching must be one of {STITCHING}")
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device).eval()
        self.max_length, self.overlap, self.batch_size, self.threshold = max_length, overlap, batch_size, threshold
        self.stitching = stitching
        self.o_id = self.model.config.label2id["O"]

    @torch.inference_mode()
    def token_predictions(self, texts: list[str]) -> list[list[TokenPred]]:
        encoded = [encode_text(self.tokenizer, t) for t in texts]
        jobs = []  # (doc index, window, model input ids)
        for d, enc in enumerate(encoded):
            for w in inference_windows(len(enc.input_ids), self.max_length, self.overlap, self.stitching):
                jobs.append((d, w, wrap_window(self.tokenizer, enc.input_ids, w, self.max_length)))
        jobs.sort(key=lambda j: len(j[2]))
        probs_per_doc = [[None] * len(enc.input_ids) for enc in encoded]
        pad_id = self.tokenizer.pad_token_id
        for i in range(0, len(jobs), self.batch_size):
            batch = jobs[i:i + self.batch_size]
            width = max(len(j[2]) for j in batch)
            ids = torch.full((len(batch), width), pad_id, dtype=torch.long)
            mask = torch.zeros((len(batch), width), dtype=torch.long)
            for row, (_, _, input_ids) in enumerate(batch):
                ids[row, :len(input_ids)] = torch.tensor(input_ids)
                mask[row, :len(input_ids)] = 1
            logits = self.model(input_ids=ids.to(self.device), attention_mask=mask.to(self.device)).logits
            probs = torch.softmax(logits.float(), dim=-1).cpu()
            for row, (d, w, _) in enumerate(batch):
                # position 0 is the leading special token
                for tok in w.owned:
                    probs_per_doc[d][tok] = probs[row, 1 + tok - w.context_start]
        out = []
        for enc, doc_probs in zip(encoded, probs_per_doc):
            rows = []
            for (start, end), p in zip(enc.offsets, doc_probs):
                p_o = float(p[self.o_id])
                p_rest = p.clone()
                p_rest[self.o_id] = -1.0
                best = int(torch.argmax(p_rest))
                rows.append((start, end, p_o, best, float(p[best])))
            out.append(rows)
        return out

    def detect_batch(self, texts: list[str]) -> list[list[Span]]:
        return [decode(tp, self.threshold) for tp in self.token_predictions(texts)]

    def detect(self, text: str) -> list[Span]:
        return self.detect_batch([text])[0]
