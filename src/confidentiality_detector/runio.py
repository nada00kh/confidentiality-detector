"""Prediction files and run metadata shared by predict/evaluate scripts."""

from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path

from .decoding import decode
from .documents import Span, file_sha256, read_jsonl, write_jsonl

EVAL_SETS = (
    "validation", "test", "test_unseen_context", "test_unseen_value", "test_novel_template",
    "test_familiar_template", "test_format_shift", "test_long", "challenge_v1",
)


def manifest_sets(eval_dir: Path) -> list[str]:
    """Evaluation sets declared by <eval_dir>/manifest.json (falls back to EVAL_SETS)."""
    manifest = Path(eval_dir) / "manifest.json"
    if manifest.exists():
        return list(json.loads(manifest.read_text(encoding="utf-8"))["sets"])
    return list(EVAL_SETS)


class ProvenanceError(RuntimeError):
    """Predictions were made on a different version of the evaluation set."""


def check_provenance(pred_dir: Path, set_name: str, eval_path: Path) -> None:
    """Refuse to score predictions against an evaluation file they were not made on.

    predict.py records the sha256 of every evaluation file in <pred_dir>/run_info.json. Reusing
    predictions on another version of a set is only allowed through
    scripts/retarget_predictions.py, which verifies that every document text is identical."""
    info_path = Path(pred_dir) / "run_info.json"
    if not info_path.exists():
        raise ProvenanceError(f"{pred_dir}: no run_info.json, cannot verify which evaluation file was predicted")
    record = json.loads(info_path.read_text(encoding="utf-8")).get("sets", {}).get(set_name)
    actual = file_sha256(eval_path)
    if record is None or record.get("eval_sha256") != actual:
        raise ProvenanceError(
            f"{pred_dir.name}/{set_name}: predictions were made on eval sha256 "
            f"{(record or {}).get('eval_sha256', 'unknown')[:12]}, but {eval_path} is {actual[:12]}. "
            "Re-run prediction, or use scripts/retarget_predictions.py if the texts are identical.")


def save_predictions(path: Path, doc_ids, spans_per_doc, tokens_per_doc=None) -> None:
    def rows():
        for i, doc_id in enumerate(doc_ids):
            row = {"doc_id": doc_id, "spans": [[s.start, s.end, s.label, None if s.score is None else round(s.score, 4)]
                                               for s in spans_per_doc[i]]}
            if tokens_per_doc is not None:
                row["tokens"] = [[s, e, round(p_o, 5), best, round(p_b, 5)] for s, e, p_o, best, p_b in tokens_per_doc[i]]
            yield row

    write_jsonl(path, rows())


def load_predictions(path: Path, threshold: float | None = None, redecode: bool = False) -> dict[str, list[Span]]:
    """Spans per doc. With redecode=True (or a threshold) spans are rebuilt from stored token
    probabilities, which must then be present."""
    out = {}
    for row in read_jsonl(path):
        if redecode or threshold is not None:
            if "tokens" not in row:
                raise ValueError(f"{path}: no token probabilities stored; cannot re-decode")
            out[row["doc_id"]] = decode([tuple(t) for t in row["tokens"]], threshold)
        else:
            out[row["doc_id"]] = [Span(s, e, label, score) for s, e, label, score in row["spans"]]
    return out


def environment_info() -> dict:
    info = {"python": platform.python_version(), "platform": platform.platform()}
    for module in ("torch", "transformers", "datasets", "presidio_analyzer", "spacy", "phonenumbers"):
        try:
            info[module] = __import__(module).__version__
        except Exception:
            pass
    try:
        info["git_commit"] = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                            cwd=Path(__file__).parent).stdout.strip()
    except Exception:
        pass
    return info


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=_default), encoding="utf-8")


def _default(o):
    try:
        import numpy as np

        if isinstance(o, np.generic):
            return o.item()
    except ImportError:
        pass
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(type(o))
