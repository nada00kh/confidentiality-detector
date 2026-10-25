# Case-file format (dev_v1, challenge_v1, challenge_v2)

Plain UTF-8 text. One file holds many cases. Parsed by `src/confidentiality_detector/challenge.py`.

```
# lines before the first case are a free-form preamble
# a line like "# ======" or "# ------" between cases is a section separator (only blank lines may follow it)

@@ <case-id> | <tag>,<tag>,... | <BLOCK|ALLOW|AMBIGUOUS>
The case text, over as many lines as needed, with inline annotations:
[[LABEL:value]]   target entity        e.g. [[EMAIL:jane.doe@example.org]]
[[!TYPE:value]]   out-of-scope look-alike (hard negative), e.g. [[!TRACKING:1Z999AA10123456784]]
[[~TYPE:value]]   ambiguous span (not scored), e.g. [[~AMBIG:127.0.0.1]]
```

**Header**
* `case-id`: letters, digits, `_`, `-`; unique in the file.
* `tags`: comma-separated, no spaces. Used for per-category reporting.
* The decision field (`BLOCK` / `ALLOW` / `AMBIGUOUS`) is **required for challenge_v2** and optional for the older files.

**Annotations**
* `LABEL` must be one of the 13 target labels. `TYPE` after `!` or `~` is free-form, upper case recommended.
* `~` is only for genuinely undecidable values. Out-of-scope credentials (API keys, tokens) are look-alikes, `[[!APIKEY:…]]`, so that predicting PASSWORD on them is scored as a false positive (decision F). The `challenge_v2` validator rejects `~SECRET`, `~APIKEY`, `~TOKEN` and similar. The frozen `challenge_v1` still contains one `~SECRET`; the overlay behind `challenge_v1_final` re-scores it.
* The value is copied verbatim into the text, and the span is computed automatically, so offsets are never written by hand.
* A value must not contain `]]`. A value may contain `:` (only the first `:` separates label and value).

**Decision consistency** (checked by the parser; inconsistency is an error):
* `BLOCK` requires at least one target annotation.
* `ALLOW` and `AMBIGUOUS` require none: any target entity means BLOCK under the policy.
* Use `AMBIGUOUS` for a case whose correct decision is genuinely unclear, and explain why in a `~` annotation type or in a tag.

**Lines.** The file is UTF-8 without a byte-order mark; LF and CRLF line endings are both fine.
* The text of a case runs from the line after its header to the line before the next header. Leading and trailing blank lines are removed. A blank line inside a case is kept.
* A separator line (`#` followed by three or more `-` or `=`) is dropped. It does not end a case: any line after it, up to the next header, is text of the case above.
* A line starting with `# ` directly after a header is dropped. After a blank line it is case text.
* A line starting with `@@` that is not a valid header is case text. A unified-diff hunk header (`@@ -1,2 +1,2 @@`) is always case text.
* Unicode line separators (U+2028, form feed, NEL) inside a line are kept verbatim.

**Strict parsing (challenge_v2).** These rules let a slip pass silently: a lost first case, a merged case, a dropped line. Every `challenge_v2.py` command therefore parses with `read_case_file(path, strict=True)` and lists every problem at once, by line number and case id, never with text:

| Error (validation fails) | What the lenient parser does |
|---|---|
| byte-order mark at the start of the file, or bytes that are not UTF-8 | BOM: the first header is not recognised and the first case is lost |
| malformed header: `@@` followed by something id-like that does not match the grammar (lowercase decision, spaces in the tags, extra field, leading whitespace, …) | the line and its whole case join the previous case |
| a `# ` line directly after a header | the line, with any annotation on it, is dropped |
| a separator line followed by text before the next header | the separator is dropped and the text (often a comment between cases) joins the case above |
| a separator line with annotation markup | the line and its annotation are dropped |
| per-case errors (unknown label, leftover markup, inconsistent decision, overlapping targets) and duplicate ids | stops at the first one |

| Warning (review it) | Why |
|---|---|
| `#` comment lines that end a case after a blank line | case text, but possibly meant as a comment about the next case |
| annotation markup before the first header | the preamble is ignored: is the first header missing? |
| empty case text | usually a slip |

The frozen development files (`dev_v1`, `challenge_v1`) pass the strict checks and parse identically in both modes (tests/test_challenge_v2.py).

Example:

```
@@ ex-001 | enterprise,structured | BLOCK
{"user": "[[USERNAME:svc_ingest]]", "password": "[[PASSWORD:Ing3st!Now]]", "build": "[[!VERSION:4.12.0]]"}

@@ ex-002 | lookalike | ALLOW
Tracking [[!TRACKING:1Z999AA10123456784]] has not moved since Monday.

@@ ex-003 | lookalike,cvv | AMBIGUOUS
The sticky note just says [[~AMBIG:482]].
```
