"""Document/span data model and (de)serialisation.

A Document is the unit of splitting, evaluation, and BLOCK/ALLOW decisions. Windows are
derived from documents *after* splitting, never before.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from .labels import LabelPolicy, Role, V2, cvv_has_evidence


@dataclass(frozen=True, order=True)
class Span:
    start: int
    end: int
    label: str
    score: float | None = field(default=None, compare=False)

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end

    def key(self) -> tuple[int, int, str]:
        return (self.start, self.end, self.label)


@dataclass
class Document:
    doc_id: str
    text: str
    spans: list[Span]                                         # target entities (gold)
    ignore_spans: list[Span] = field(default_factory=list)    # neither rewarded nor penalised
    negative_spans: list[Span] = field(default_factory=list)  # out-of-scope entities (hard negatives)
    meta: dict = field(default_factory=dict)

    @property
    def should_block(self) -> bool:
        return bool(self.spans)

    def gold_decision(self) -> str:
        """Document-level ground truth: an explicit meta["expected"] (case files with a
        decision field) wins; otherwise BLOCK iff a target span exists, AMBIGUOUS if only
        ignore spans exist, else ALLOW."""
        expected = self.meta.get("expected")
        if expected:
            return expected
        if self.spans:
            return "BLOCK"
        return "AMBIGUOUS" if self.ignore_spans else "ALLOW"

    def validate(self) -> None:
        for span in self.spans + self.ignore_spans + self.negative_spans:
            if not (0 <= span.start < span.end <= len(self.text)):
                raise ValueError(f"{self.doc_id}: span {span} out of bounds")
        ordered = sorted(self.spans)
        for a, b in zip(ordered, ordered[1:]):
            if a.overlaps(b):
                raise ValueError(f"{self.doc_id}: overlapping target spans {a} / {b}")

    def to_json(self) -> dict:
        def spans(items):
            return [[s.start, s.end, s.label] for s in items]

        return {
            "doc_id": self.doc_id,
            "text": self.text,
            "spans": spans(self.spans),
            "ignore_spans": spans(self.ignore_spans),
            "negative_spans": spans(self.negative_spans),
            "meta": self.meta,
        }

    @classmethod
    def from_json(cls, row: dict) -> "Document":
        def spans(items):
            return [Span(int(s), int(e), str(label)) for s, e, label in items]

        return cls(
            doc_id=str(row["doc_id"]),
            text=row["text"],
            spans=spans(row.get("spans", [])),
            ignore_spans=spans(row.get("ignore_spans", [])),
            negative_spans=spans(row.get("negative_spans", [])),
            meta=row.get("meta", {}),
        )


def document_from_ai4privacy(record: dict, policy: LabelPolicy = V2) -> Document:
    """Convert one ai4privacy record (source_text + privacy_mask) using a label policy."""
    text = record["source_text"]
    buckets: dict[Role, list[Span]] = {role: [] for role in Role}
    card_spans = [(a["start"], a["end"]) for a in record["privacy_mask"]
                  if a["label"] in ("CREDITCARDNUMBER", "MASKEDNUMBER")]
    for ann in record["privacy_mask"]:
        if text[ann["start"]:ann["end"]] != ann["value"]:
            raise ValueError(f"record {record.get('id')}: span/value mismatch for {ann['label']}")
        role, label = policy.resolve(ann["label"], ann["value"])
        if (role is Role.TARGET and label == "CREDITCARDCVV" and policy.cvv_requires_evidence
                and not cvv_has_evidence(text, ann["start"], ann["end"], card_spans)):
            role, label = Role.IGNORE, "CVV_NO_EVIDENCE"
        buckets[role].append(Span(ann["start"], ann["end"], label))
    doc = Document(
        doc_id=str(record["id"]),
        text=text,
        spans=sorted(buckets[Role.TARGET]),
        ignore_spans=sorted(buckets[Role.IGNORE]),
        negative_spans=sorted(buckets[Role.NEGATIVE]),
        meta={"source": "ai4privacy", "policy": policy.name},
    )
    doc.validate()
    return doc


def read_jsonl(path: str | Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def load_documents(path: str | Path) -> list[Document]:
    docs = [Document.from_json(row) for row in read_jsonl(path)]
    for doc in docs:
        doc.validate()
    return docs


def save_documents(path: str | Path, docs: Iterable[Document]) -> int:
    return write_jsonl(path, (d.to_json() for d in docs))


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def span_dicts(spans: Iterable[Span]) -> list[dict]:
    return [asdict(s) for s in spans]
