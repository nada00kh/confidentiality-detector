"""Value-format perturbation of documents (exact offset bookkeeping).

Two *disjoint* format families are defined per label:
  * family "A" may be used to augment TRAINING documents;
  * family "B" is reserved for EVALUATION (test_format_shift) and never used in training.
So a model trained with family-A augmentation is still evaluated on formats it never saw.
All values are synthetic (generated here); card numbers are Luhn-valid and IBANs are
checksum-valid so that they look like real identifiers, unlike much of the source data.
"""

from __future__ import annotations

import hashlib
import random
import string
import unicodedata
from typing import Callable

from .documents import Document, Span

# Name pools: filtered at build time against the training-set name vocabulary.
FIRST_NAMES_A = """Aarav Bilal Chidi Dmitri Esperanza Farida Goran Hamid Ingrid Jun Kemal Leilani Mateus
Nkechi Oksana Pradeep Quang Rashida Sione Thandiwe Ulrich Valentina Wanjiru Ximena Yusuf Zainab""".split()
LAST_NAMES_A = """Abubakar Bergström Castellanos Dlamini Eriksen Fujimoto Gonçalves Haddad Ivanova Jankowski
Kowalczyk Lindqvist Mahlangu Nakamura Okonkwo Petrović Quispe Rahimi Szabo Takahashi Uchenna Vasquez
Wiśniewski Xu Yilmaz Zapata""".split()
FIRST_NAMES_B = """Adaeze Bongani Chiamaka Dagny Emeka Fenna Gulnara Hoang Ifeoma Jaroslav Kaveh Lerato
Mirela Nnamdi Olumide Pania Radhika Saoirse Tamar Uzoma Vuong Wiremu Yerlan Zhenya Anouk Bartosz""".split()
LAST_NAMES_B = """Adeyemi Bajwa Chukwu Dzhumabaev Esposito Fagerlund Ghosh Hakobyan Iwu Jovanović
Kariuki Lungu Mbeki Nwosu Oyelaran Pham Rautenbach Sandoval Tshabalala Umarov Vukovic Wainwright
Yamamoto Zielinski Achterberg Bhattacharya""".split()
STREETS_A = """Juniper Hollow|Kestrel Way|Old Mill Road|Larkspur Lane|Quarry Hill Drive|Saddleback Court|
Bramble Terrace|Copperfield Avenue|Heron Bay Boulevard|Windmill Close""".replace("\n", "").split("|")
STREETS_B = """5th Avenue|Martin Luther King Jr Blvd|N Clark St|Rue de Rivoli|Calle Mayor|Avenida Paulista|
Princes St|W 34th Street|Ocean Pkwy|Route 9W""".replace("\n", "").split("|")
DOMAINS_A = ["northwind-analytics.com", "contoso.org", "fabrikam.io", "tailspin.net"]
DOMAINS_B = ["mail.adatum.co.uk", "corp.litware.de", "eng.wingtip.dev", "student.uni-example.edu"]
PASSWORD_WORDS = ["Summer", "Falcon", "Orange", "Winter", "Tiger", "Coffee", "Rocket", "Maple"]


def _rng(*parts: str) -> random.Random:
    seed = int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def luhn_complete(prefix_digits: str, length: int, rng: random.Random) -> str:
    body = prefix_digits + "".join(rng.choice(string.digits) for _ in range(length - len(prefix_digits) - 1))
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return body + str((10 - total % 10) % 10)


def iban_complete(country: str, bban: str) -> str:
    rearranged = bban + country + "00"
    check = 98 - int("".join(str(int(c, 36)) for c in rearranged)) % 97
    return f"{country}{check:02d}{bban}"


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


def _group(s: str, sizes: list[int], sep: str) -> str:
    out, i = [], 0
    for size in sizes:
        out.append(s[i:i + size])
        i += size
    if i < len(s):
        out.append(s[i:])
    return sep.join(p for p in out if p)


def _card(rng: random.Random, family: str) -> str:
    brand = rng.choice(["visa", "mc", "amex", "discover"])
    if brand == "amex":
        num = luhn_complete(rng.choice(["34", "37"]), 15, rng)
        return _group(num, [4, 6, 5], "-" if family == "A" else " ")
    prefix = {"visa": "4", "mc": str(rng.randint(51, 55)), "discover": "6011"}[brand]
    num = luhn_complete(prefix, 16, rng)
    if family == "A":
        return rng.choice([num, _group(num, [4, 4, 4, 4], "-")])
    return _group(num, [4, 4, 4, 4], " ")


def _phone(rng: random.Random, family: str) -> str:
    a, b, c = str(rng.randint(201, 989)), "555", "01" + _digits(rng, 2)
    if family == "A":
        return rng.choice([f"({a}) {b}-{c}", f"{a}-{b}-{c}"])
    return rng.choice([f"+1 {a} {b} {c}", f"+44 20 {_digits(rng, 4)} {_digits(rng, 4)}", f"1-800-{b}-{c}", f"+49 30 {_digits(rng, 8)}"])


def _ascii(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return "".join(c for c in folded.lower() if c.isalnum())


def _email(rng, family, first, last):
    first, last = _ascii(first), _ascii(last)
    if family == "A":
        local = rng.choice([f"{first}.{last}", f"{first[0]}{last}", f"{first}_{last}"])
        return f"{local}@{rng.choice(DOMAINS_A)}"
    local = rng.choice([f"{first[0]}.{last}+billing", f"{last}{rng.randint(1, 99)}", f"{first}-{last[:3]}"])
    return f"{local}@{rng.choice(DOMAINS_B)}"


def _username(rng, family, first, last):
    first, last = _ascii(first), _ascii(last)
    if family == "A":
        return rng.choice([f"{first[0]}{last}", f"{last}_{first[0]}", f"{first}{last[:2]}"])
    return rng.choice([f"dev-{last}_{rng.randint(1, 99)}", f"x_{first[0]}{last}", f"{first[0]}{last[:4]}.admin"])


def _password(rng: random.Random, family: str) -> str:
    if family == "A":
        return f"{rng.choice(PASSWORD_WORDS)}{rng.randint(1990, 2026)}{rng.choice('!#$%')}"
    leet = str.maketrans({"a": "@", "o": "0", "e": "3", "s": "$", "i": "1"})
    word = rng.choice(["password", "letmein", "dragonfly", "sunshine", "princess", "trustno"]).translate(leet)
    return rng.choice([word + _digits(rng, 2), word.capitalize() + "#" + _digits(rng, 3), word[:6] + "&" + _digits(rng, 1)])


def _iban(rng: random.Random, family: str) -> str:
    country, bban = rng.choice([("DE", _digits(rng, 18)), ("GB", "WEST" + _digits(rng, 14)), ("FR", _digits(rng, 23)), ("NL", "ABNA" + _digits(rng, 10))])
    iban = iban_complete(country, bban)
    return iban if family == "A" else _group(iban, [4] * 9, " ")


def _account(rng: random.Random, family: str) -> str:
    if family == "A":
        return _digits(rng, rng.choice([10, 11, 12]))
    return rng.choice([f"{_digits(rng, 4)}-{_digits(rng, 6)}", f"{_digits(rng, 3)}-{_digits(rng, 6)}-{_digits(rng, 2)}", _digits(rng, 14)])


def _cvv(rng: random.Random, family: str) -> str:
    return _digits(rng, 3) if family == "A" else _digits(rng, 4)


class FormatPerturber:
    """Re-render target values of a document in family A or B formats."""

    def __init__(self, family: str, excluded_names: set[str] = frozenset()):
        if family not in ("A", "B"):
            raise ValueError("family must be 'A' or 'B'")
        self.family = family
        lower = {n.lower() for n in excluded_names}
        firsts = FIRST_NAMES_A if family == "A" else FIRST_NAMES_B
        lasts = LAST_NAMES_A if family == "A" else LAST_NAMES_B
        self.first_names = [n for n in firsts if n.lower() not in lower]
        self.last_names = [n for n in lasts if n.lower() not in lower]
        self.streets = STREETS_A if family == "A" else STREETS_B

    def render(self, label: str, original: str, rng: random.Random, person: tuple[str, str]) -> str | None:
        f = self.family
        first, last = person
        renderers: dict[str, Callable[[], str]] = {
            "CREDITCARDNUMBER": lambda: _card(rng, f),
            "PHONENUMBER": lambda: _phone(rng, f),
            "EMAIL": lambda: _email(rng, f, first, last),
            "USERNAME": lambda: _username(rng, f, first, last),
            "PASSWORD": lambda: _password(rng, f),
            "IBAN": lambda: _iban(rng, f),
            "ACCOUNTNUMBER": lambda: _account(rng, f),
            "CREDITCARDCVV": lambda: _cvv(rng, f),
            "FIRSTNAME": lambda: first.lower() if (f == "B" and rng.random() < 0.3) else first,
            "LASTNAME": lambda: last,
            "STREET": lambda: rng.choice(self.streets),
        }
        fn = renderers.get(label)
        return fn() if fn else None  # SSN / IPV4 keep their value

    def __call__(self, doc: Document, suffix: str = "") -> Document:
        rng = _rng(doc.doc_id, self.family, suffix)
        person = (rng.choice(self.first_names), rng.choice(self.last_names))
        replacements = {}
        for span in doc.spans:
            new = self.render(span.label, doc.text[span.start:span.end], rng, person)
            if new is not None:
                replacements[(span.start, span.end)] = new
        text, mapping = _apply(doc.text, replacements)

        def remap(spans: list[Span]) -> list[Span]:
            return [Span(mapping[(s.start, "s")], mapping[(s.end, "e")], s.label) for s in spans]

        all_points = {(s.start, "s") for s in doc.spans + doc.ignore_spans + doc.negative_spans} | {
            (s.end, "e") for s in doc.spans + doc.ignore_spans + doc.negative_spans
        }
        missing = [p for p in all_points if p not in mapping]
        if missing:
            raise ValueError(f"{doc.doc_id}: unmapped offsets {missing[:3]}")
        new_doc = Document(
            doc_id=f"{doc.doc_id}~fmt{self.family}{suffix}",
            text=text,
            spans=remap(doc.spans),
            ignore_spans=remap(doc.ignore_spans),
            negative_spans=remap(doc.negative_spans),
            meta={**doc.meta, "perturbation": f"format_{self.family}", "parent": doc.doc_id},
        )
        new_doc.validate()
        for old, new in zip(doc.spans, new_doc.spans):
            expected = replacements.get((old.start, old.end), doc.text[old.start:old.end])
            assert new_doc.text[new.start:new.end] == expected
        return new_doc


def _apply(text: str, replacements: dict[tuple[int, int], str]) -> tuple[str, dict]:
    """Apply non-overlapping replacements; return new text and a map from every old
    boundary offset (tagged start/end) to its new position."""
    out, mapping, cursor, shift = [], {}, 0, 0
    boundaries = sorted(replacements)
    for (start, end) in boundaries:
        out.append(text[cursor:start])
        new = replacements[(start, end)]
        out.append(new)
        cursor = end
    out.append(text[cursor:])
    new_text = "".join(out)

    # Build offset map: positions outside replaced regions shift by the cumulative delta.
    deltas = []
    total = 0
    for (start, end) in boundaries:
        deltas.append((start, end, total, total + len(replacements[(start, end)]) - (end - start)))
        total += len(replacements[(start, end)]) - (end - start)

    def shift_point(pos: int, kind: str) -> int:
        d = 0
        for start, end, before, after in deltas:
            if pos <= start:
                return pos + before
            if pos == end and kind == "e":
                return pos + after
            if start < pos < end:
                raise ValueError("offset inside replaced region")
            d = after
        return pos + d

    for pos in range(len(text) + 1):
        for kind in ("s", "e"):
            try:
                mapping[(pos, kind)] = shift_point(pos, kind)
            except ValueError:
                pass
    return new_text, mapping
