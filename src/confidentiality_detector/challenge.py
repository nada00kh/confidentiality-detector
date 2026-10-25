"""Parser for the hand-written case files (data/dev/dev_v1.txt, data/challenge/challenge_v*.txt).

The format is described in docs/CASE_FORMAT.md. load_challenge(path) keeps the historical, lenient
behaviour on which the frozen development files were parsed. strict=True (challenge_v2) reports the
constructs that the lenient parser drops or merges without a word; see read_case_file. Problems
name line numbers, case ids and error types, never case text.
"""

from __future__ import annotations

import codecs
import re
from collections import Counter
from pathlib import Path

from .documents import Document, Span
from .labels import TARGET_SET

HEADER_RE = re.compile(r"^@@\s*(?P<id>[\w-]+)\s*\|\s*(?P<tags>[\w,-]*)\s*(?:\|\s*(?P<expected>BLOCK|ALLOW|AMBIGUOUS)\s*)?$")
MARK_RE = re.compile(r"\[\[(?P<kind>[~!]?)(?P<label>[A-Za-z0-9_-]+):(?P<value>.+?)\]\]")
SEPARATOR_RE = re.compile(r"^#\s*[-=]{3,}")  # section separator line ("# ======"); dropped
# "@@" followed by something id-like is meant to be a case header; a unified-diff hunk header
# ("@@ -1,3 +1,4 @@") is ordinary case text.
HEADER_LIKE_RE = re.compile(r"^[ \t﻿]*@@\s*[\w-]")
DIFF_HUNK_RE = re.compile(r"^\s*@@@? -\d")
COMMENT_RE = re.compile(r"^#+(?:\s|$)")
DECISIONS = ("BLOCK", "ALLOW", "AMBIGUOUS")
HEADER_GRAMMAR = "'@@ <id> | <tag>,<tag> | BLOCK|ALLOW|AMBIGUOUS'"


class CaseFileError(ValueError):
    """Every error found in a case file, one per line (line numbers, case ids, error types; no text)."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


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


def _header_problem(line: str) -> str:
    """Why a header-like line does not match the header grammar (without echoing the line)."""
    if line[:1] in (" ", "\t", "﻿"):
        return "whitespace or a byte-order mark before '@@'"
    fields = [f.strip() for f in line.strip()[2:].split("|")]
    if len(fields) < 2:
        return "missing '|' separators"
    if len(fields) > 3:
        return "more than three '|'-separated fields"
    if not re.fullmatch(r"[\w-]+", fields[0]):
        return "the case id may contain only letters, digits, '_' and '-'"
    if re.search(r"\s", fields[1]):
        return "spaces in the tag list"
    if not re.fullmatch(r"[\w,-]*", fields[1]):
        return "the tags may contain only letters, digits, '_', '-' and ','"
    if len(fields) == 3:
        words = fields[2].split()
        if len(words) > 1 and words[0] in DECISIONS:
            return "nothing may follow the decision"
        if fields[2].upper() in DECISIONS:
            return "the decision must be upper case"
        return "the decision must be BLOCK, ALLOW or AMBIGUOUS"
    return "it does not match the header grammar"


def read_case_file(path: str | Path, strict: bool = False) -> tuple[list[Document], list[str], list[str]]:
    """Parse a case file into (documents, errors, warnings).

    strict=False is the historical parser: the first problem raises ValueError, and the constructs
    below pass silently. strict=True collects every error instead of raising, and adds:
      errors   - a UTF-8 byte-order mark (it hides the first header, so the first case is lost),
                 or bytes that are not UTF-8;
               - a malformed header (lenient: the line and its whole case join the previous case);
               - a '# ' line directly after a header (dropped);
               - a separator line followed by text before the next header (the separator is
                 dropped and the text, typically a comment between cases, joins the case);
               - annotation markup on a dropped separator line;
      warnings - '#' comment lines that end a case after a blank line: they are part of its text,
                 but may have been meant as a comment about the next case;
               - annotation markup in the preamble (is the first header missing?).
    Splitting is the same in both modes, so a file without errors parses identically."""
    errors: list[str] = []
    warnings: list[str] = []

    def problem(message: str) -> None:
        if strict:
            errors.append(message)

    raw = Path(path).read_bytes()
    if strict and raw.startswith(codecs.BOM_UTF8):
        problem("the file starts with a UTF-8 byte-order mark (BOM): save it as UTF-8 without BOM "
                "(otherwise the first case header is not recognised and the first case is lost)")
        raw = raw[len(codecs.BOM_UTF8):]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        if not strict:
            raise
        hint = " (it looks like UTF-16)" if raw[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE) else ""
        errors.append(f"the file is not valid UTF-8{hint}: first invalid byte at offset {exc.start}; "
                      "save it as UTF-8 without BOM")
        return [], errors, warnings
    # Line endings as Path.read_text normalises them. Split on "\n" only: str.splitlines() also
    # breaks at U+2028, form feeds and similar characters and would turn them into newlines.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    cases: list[dict] = []
    current: dict | None = None
    skipping = False  # strict: the lines under a malformed header belong to no case
    for lineno, line in enumerate(text.split("\n"), 1):
        header = HEADER_RE.match(line)
        if header:
            current = {"id": header.group("id"), "tags": [t for t in header.group("tags").split(",") if t],
                       "expected": header.group("expected"), "line": lineno, "lines": [],
                       "separator": None, "dropped_comment": False}
            cases.append(current)
            skipping = False
            continue
        if HEADER_LIKE_RE.match(line) and not DIFF_HUNK_RE.match(line):
            where = f"it would silently join case {current['id']}" if current else "it would be ignored as preamble"
            problem(f"line {lineno}: malformed case header ({_header_problem(line)}); expected {HEADER_GRAMMAR}; {where}")
            if strict:
                current, skipping = None, True
                continue
        if skipping:
            continue
        if line.startswith("# ") and current is not None and not current["lines"]:
            if not current["dropped_comment"]:
                problem(f"case {current['id']}: line {lineno} starts with '# ' directly after the header and is dropped; "
                        "put notes in the preamble (if it is case text, insert a blank line after the header)")
                current["dropped_comment"] = True
            continue
        if current is None:
            if "[[" in line:
                warnings.append(f"line {lineno}: annotation markup before the first case header (the preamble is "
                                "ignored); is the first header missing or malformed?")
            continue
        if SEPARATOR_RE.match(line):
            if "[[" in line:
                problem(f"case {current['id']}: separator line {lineno} contains annotation markup and is dropped")
            current["separator"] = current["separator"] or lineno
            continue
        if line.strip() and current["separator"]:
            problem(f"case {current['id']}: separator line {current['separator']} is followed by text (line {lineno}) "
                    f"before the next header; the separator is dropped and the text becomes part of case {current['id']}. "
                    "Comments between cases are not allowed (put notes in the preamble), and a case must not contain "
                    "separator lines")
            current["separator"] = None
        current["lines"].append((lineno, line))

    for case in cases:
        lines = case["lines"]
        filled = [i for i, (_, line) in enumerate(lines) if line.strip()]
        if not filled:
            continue
        j = filled[-1]
        while j >= 0 and lines[j][1].strip() and COMMENT_RE.match(lines[j][1]):
            j -= 1
        if j < filled[-1] and j > 0 and not lines[j][1].strip() and any(line.strip() for _, line in lines[:j]):
            warnings.append(f"case {case['id']}: ends with '#' comment line(s) after a blank line (from line "
                            f"{lines[j + 1][0]}); they are part of the case text. If they are a comment about the "
                            "next case, move it to the preamble")

    docs: list[Document] = []
    for case in cases:
        body = "\n".join(line for _, line in case["lines"]).strip("\n")
        try:
            docs.append(parse_case(case["id"], case["tags"], body, case["expected"]))
        except ValueError as exc:
            if not strict:
                raise
            errors.append(str(exc))
    counts = Counter(case["id"] for case in cases)
    duplicates = [case_id for case_id, n in counts.items() if n > 1]
    if duplicates:
        message = "duplicate case ids: " + "; ".join(
            f"{case_id} (lines {', '.join(str(c['line']) for c in cases if c['id'] == case_id)})" for case_id in duplicates)
        if not strict:
            raise ValueError(message)
        errors.append(message)
    for doc in docs:
        doc.meta["tags"] = sorted(set(doc.meta["tags"]) | {doc.gold_decision().lower()})
    return docs, errors, warnings


def load_challenge(path: str | Path, strict: bool = False) -> list[Document]:
    """The documents of a case file. strict=True raises CaseFileError listing every error that
    read_case_file finds; the default keeps the historical behaviour (see read_case_file)."""
    docs, errors, _ = read_case_file(path, strict)
    if errors:
        raise CaseFileError(errors)
    return docs
