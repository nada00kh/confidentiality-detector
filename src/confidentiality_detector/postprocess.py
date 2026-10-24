"""Optional post-processing of MODEL spans before they are reconciled with the rules.

Only one step exists, and it is off by default (configs/inference/policy.json, `postprocessing`):

ipv4_requires_valid_address
    A model span labelled IPV4 is kept only if it overlaps a complete IPv4 address in the text
    (four decimal octets 0-255, not part of a longer dotted or digit sequence). Fragments the
    model cuts out of version numbers or other dotted identifiers ("…4.12.0" -> ".12.0") are
    dropped. Rule findings are never touched (the rules validate IPv4 themselves), and no other
    label is affected; in particular there is no validation gate for IBAN, card numbers or SSNs
    (not approved: a failed checksum must not let a possibly sensitive value through).
    Adoption is decided by the pre-registered study in docs/METHODOLOGY.md section 8.
"""

from __future__ import annotations

import re
from typing import Sequence

from .documents import Span

_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
# not preceded by a digit or "digit.", not followed by a digit or ".digit" (a trailing full stop is fine)
IPV4_ADDRESS_RE = re.compile(rf"(?<!\d)(?<!\d\.){_OCTET}(?:\.{_OCTET}){{3}}(?!\d)(?!\.\d)")


def ipv4_addresses(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in IPV4_ADDRESS_RE.finditer(text)]


def ipv4_gate(text: str, spans: Sequence[Span]) -> list[Span]:
    """Drop model IPV4 spans that overlap no complete IPv4 address; keep everything else."""
    if not any(s.label == "IPV4" for s in spans):
        return list(spans)
    addresses = ipv4_addresses(text)
    return [s for s in spans if s.label != "IPV4" or any(a < s.end and s.start < b for a, b in addresses)]
