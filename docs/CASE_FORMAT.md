# Case-file format (dev_v1, challenge_v1, challenge_v2)

Plain UTF-8 text. One file holds many cases. Parsed by `src/confidentiality_detector/challenge.py`.

```
# lines before the first case are a free-form preamble
# a line like "# ======" or "# ------" between cases is a section separator

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

The text of a case runs from the line after its header to the line before the next header or separator. Leading and trailing blank lines are removed. A blank line inside a case is kept.

Example:

```
@@ ex-001 | enterprise,structured | BLOCK
{"user": "[[USERNAME:svc_ingest]]", "password": "[[PASSWORD:Ing3st!Now]]", "build": "[[!VERSION:4.12.0]]"}

@@ ex-002 | lookalike | ALLOW
Tracking [[!TRACKING:1Z999AA10123456784]] has not moved since Monday.

@@ ex-003 | lookalike,cvv | AMBIGUOUS
The sticky note just says [[~AMBIG:482]].
```
