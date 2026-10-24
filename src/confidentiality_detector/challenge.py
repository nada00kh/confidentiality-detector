"""Parser for the hand-written challenge set (data/challenge/challenge_v*.txt)."""

from __future__ import annotations

import re
from pathlib import Path

from .documents import Document, Span
from .labels import TARGET_SET

HEADER_RE = re.compile(r"^@@\s*(?P<id>[\w-]+)\s*\|\s*(?P<tags>[\w,-]*)\s*(?:\|\s*(?P<expected>BLOCK|ALLOW|AMBIGUOUS)\s*)?$")
MARK_RE = re.compile(r"\[\[(?P<kind>[~!]?)(?P<label>[A-Za-z0-9_-]+):(?P<value>.+?)\]\]")


def parse_case(case_id: str, tags: list[str], body: str, expected: str | None = None) -> Document:
    text_parts: list[str] = []
    spans, ignore, negative = [], [], []
    cursor = out_len = 0
    for m in MARK_RE.finditer(body):
        literal = body[cursor:m.start()]
        text_parts.append(literal)
        out_len += len(literal)
        value = m.group("value")
        span = Span(out_len, out_len + len(value), m.group("label").upper())
        kind = m.group("kind")
        if kind == "~":
            ignore.append(span)
        elif kind == "!":
            negative.append(span)
        else:
            if span.label not in TARGET_SET:
                raise ValueError(f"{case_id}: unknown target label {span.label}")
            spans.append(span)
        text_parts.append(value)
        out_len += len(value)
        cursor = m.end()
    text_parts.append(body[cursor:])
    text = "".join(text_parts)
    if "[[" in text or "]]" in text:
        raise ValueError(f"{case_id}: unparsed markup remains")
    meta = {"source": "challenge", "tags": tags}
    if expected is not None:
        # An explicit document decision must agree with the span annotation.
        if expected == "BLOCK" and not spans:
            raise ValueError(f"{case_id}: expected BLOCK but no target span is annotated")
        if expected in ("ALLOW", "AMBIGUOUS") and spans:
            raise ValueError(f"{case_id}: expected {expected} but target spans are annotated "
                             "(a target entity always means BLOCK under the policy)")
        meta["expected"] = expected
    doc = Document(case_id, text, spans, ignore, negative, meta)
    doc.validate()
    return doc


def apply_overlay(docs: list[Document], overlay_path: str | Path, source_path: str | Path) -> list[Document]:
    """Re-annotate selected negative spans of a frozen challenge file without editing it.

    `to_target` maps a negative span's text to one target label per whitespace token;
    `to_ignore` lists negative span texts that become ignore spans;
    `ignore_to_negative` maps an ignore span's text to an out-of-scope label, so that the
    span becomes a negative: predicting a target on it is a false positive, and a document
    without targets becomes ALLOW (decision F: out-of-scope API keys are not PASSWORD)."""
    import hashlib
    import json

    overlay = json.loads(Path(overlay_path).read_text(encoding="utf-8"))
    digest = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    if digest != overlay["applies_to_sha256"]:
        raise ValueError(f"overlay targets sha256 {overlay['applies_to_sha256'][:12]}, file is {digest[:12]}")
    by_id = {d.doc_id: d for d in docs}
    out = []
    for doc in docs:
        change = overlay["changes"].get(doc.doc_id)
        if not change:
            out.append(doc)
            continue
        spans, ignore, negative = list(doc.spans), [], []
        for ign in doc.ignore_spans:
            value = doc.text[ign.start:ign.end]
            if value in change.get("ignore_to_negative", {}):
                negative.append(Span(ign.start, ign.end, change["ignore_to_negative"][value]))
            else:
                ignore.append(ign)
        for neg in doc.negative_spans:
            value = doc.text[neg.start:neg.end]
            if value in change.get("to_target", {}):
                labels = change["to_target"][value]
                tokens = [(m.start() + neg.start, m.end() + neg.start) for m in re.finditer(r"\S+", value)]
                if len(tokens) != len(labels):
                    raise ValueError(f"{doc.doc_id}: {len(tokens)} tokens vs {len(labels)} labels")
                spans += [Span(s, e, label) for (s, e), label in zip(tokens, labels)]
            elif value in change.get("to_ignore", []):
                ignore.append(Span(neg.start, neg.end, "OVERLAY_AMBIGUOUS"))
            else:
                negative.append(neg)
        used = set(change.get("to_target", {})) | set(change.get("to_ignore", []))
        found = {doc.text[n.start:n.end] for n in doc.negative_spans}
        if used - found:
            raise ValueError(f"{doc.doc_id}: overlay values not found as negative spans: {used - found}")
        unknown = set(change.get("ignore_to_negative", {})) - {doc.text[i.start:i.end] for i in doc.ignore_spans}
        if unknown:
            raise ValueError(f"{doc.doc_id}: overlay values not found as ignore spans: {unknown}")
        # (a document whose targets all became ignore spans is AMBIGUOUS but keeps the tag "allow";
        # document metrics use gold_decision(), not tags, so this only affects per-tag grouping)
        tags = sorted(set(doc.meta.get("tags", [])) - {"block", "allow"} | {"overlay"} | {"block" if spans else "allow"})
        new = Document(doc.doc_id, doc.text, sorted(spans), sorted(ignore), sorted(negative),
                       {**doc.meta, "tags": tags, "overlay": change.get("reason")})
        new.validate()
        out.append(new)
    missing = set(overlay["changes"]) - set(by_id)
    if missing:
        raise ValueError(f"overlay refers to unknown cases {missing}")
    return out


def load_challenge(path: str | Path) -> list[Document]:
    docs: list[Document] = []
    current: tuple[str, list[str]] | None = None
    lines: list[str] = []

    def flush():
        if current is not None:
            body = "\n".join(lines).strip("\n")
            docs.append(parse_case(current[0], current[1], body, current[2]))

    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        header = HEADER_RE.match(raw)
        if header:
            flush()
            tags = [t for t in header.group("tags").split(",") if t]
            current, lines = (header.group("id"), tags, header.group("expected")), []
        elif raw.startswith("# ") and current is not None and not lines:
            continue
        elif current is None:
            continue  # file preamble
        elif re.match(r"^#\s*[-=]{3,}", raw):  # section separator line
            continue
        else:
            lines.append(raw)
    flush()
    ids = [d.doc_id for d in docs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    for doc in docs:
        doc.meta["tags"] = sorted(set(doc.meta["tags"]) | {doc.gold_decision().lower()})
    return docs
