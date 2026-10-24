"""Deterministic detector: regular expressions + checksum/format validators + context cues.

Design rule: a structured identifier is reported when its *format is self-evidently
sensitive* (checksum-valid IBAN, Luhn-valid card number, dash-formatted SSN, IPv4,
e-mail address, parseable phone number) or when a nearby *context cue* says what it is
("card number", "acct #", "password:", ...). Short ambiguous digit strings (CVV, account
numbers) are only reported with a cue. Names and street addresses are left to the model.
"""

from __future__ import annotations

import re
from typing import Iterable

import phonenumbers

from ..documents import Span
from ..labels import CVV_CUE_RE, CVV_STRONG_CUE_RE, card_context

RULES_VERSION = "v3"

# Higher number wins when two rule spans overlap.
PRIORITY = {
    "EMAIL": 90, "IBAN": 85, "CREDITCARDNUMBER": 80, "SSN": 75, "IPV4": 70,
    "PASSWORD": 65, "USERNAME": 60, "PHONENUMBER": 55, "ACCOUNTNUMBER": 50,
    "CREDITCARDCVV": 45, "STREET": 40,
}

EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,24}(?![\w-])")
IPV4_RE = re.compile(r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\w]|\.\d)")
VERSION_CUE_RE = re.compile(
    r"(?i)(?:\b(?:version|ver\.?|release|build|firmware|driver|package|kernel|bios|patch)\b(?:[^\n.;]|\.(?=\d)){0,30}"
    r"|\bv)(?:\s+(?:is|was|of|=|:|from|to))?\s*$"
)
CARD_CANDIDATE_RE = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d])")
CARD_CUE_RE = re.compile(r"(?i)\b(?:credit|debit|card|visa|master\s?card|amex|american express|discover|cc|pan)\b")
IBAN_CANDIDATE_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,32}")
IMEI_RE = re.compile(r"^\d{2}-\d{6}-\d{6}-\d$")
IMEI_CUE_RE = re.compile(r"(?i)\bimei\b")
SSN_DASH_RE = re.compile(r"(?<![\d-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\d-])")
SSN_OTHER_RE = re.compile(r"(?<![\d.])\d{3}([ .]?)\d{2}\1\d{4}(?![\d.])")
SSN_CUE_RE = re.compile(r"(?i)\b(?:ssn|social security(?: number| no\.?| #)?|ss#|soc\.? sec\.?)")
# CVV: the cue vocabulary is the annotation policy's (labels.CVV_CUE_RE); the value is a
# standalone 3-4 digit number right after the cue, or right before it ("482 is the security code").
# A strong cue suffices; the weak cue ("security code") also needs card context (labels.cvv_has_evidence).
CVV_RE = re.compile(r"(?i)(?P<cue>" + CVV_CUE_RE.pattern[4:] + r")[\"']?[^\d\n]{0,25}?(?<![\d.,])(?P<value>\d{3,4})(?![\d.,]\d)")
CVV_BEFORE_CUE_RE = re.compile(r"(?i)(?<![\d.,-])(?P<value>\d{3,4})(?![\d.,-]?\d)(?=[^\d\n]{0,30}?(?P<cue>" + CVV_CUE_RE.pattern[4:] + r"))")
IP_CUE_RE = re.compile(r"(?i)\b(?:ip|ipv4|ip address|address|addr|host|server|inet|peer|client)\b\W{0,3}$")
# Network structure around a dotted quad: user@ip, scheme://ip, key=ip, ip:port, src/dst fields.
IP_STRUCTURE_BEFORE_RE = re.compile(r"(?:@|//|=|\b(?:src|dst|bind|listen|gateway|dns)\b\W{0,3})$", re.I)
DOTTED_QUAD_RE = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.]*\d)")
IP_STRUCTURE_AFTER_RE = re.compile(r"^(?::\d{1,5}\b|/\d{1,2}\b| - - \[|\s+port\b)")
# Identifier cues: a number introduced like this is a tracking/order/meeting/... id, not a phone or card.
ID_CUE_RE = re.compile(r"(?i)\b(?:tracking|track|shipment|consignment|parcel|order|po|invoice|inv|ticket|case|incident|"
                       r"meeting|bridge|conference|webinar|sku|ean|upc|gtin|barcode|serial|lot|batch|booking|confirmation|"
                       r"reference|ref|request|trace|job|build|id)\b[^\n\d]{0,12}$")
CARD_GROUPINGS = ((4, 4, 4, 4), (4, 6, 5), (4, 6, 4), (4, 4, 4, 4, 3), (4, 4, 4, 4, 2), (4, 4, 4, 3))
ACCOUNT_RE = re.compile(r"(?i)\b(?:account|acct|a/c)(?:\s*(?:number|num|no\.?|#))?\s*(?:is|was|:|#|=)?\s*(?<![\d])(\d(?:[\d -]{4,22})\d)(?![\d])")
SECRET_VALUE = r"[\"'`]?(?P<value>[^\s\"'`,;]{3,128}?)[\"'`]?(?=[\s,;}\]]|[.!?)](?:\s|$)|$)"
# A numeric "passcode" (door, locker, meeting) is a PIN, outside the 13-label scope; an
# alphanumeric one is treated as a password. An optional quote after the keyword covers JSON/YAML keys.
PASSWORD_RE = re.compile(
    r"(?i)(?<![A-Za-z])(?P<kw>password|passwd|passwort|passphrase|passcode|pass|pwd|pw)[\"']?"
    r"(?P<sep>\s+(?:is|was|to|of)\b\s*|\s*[:=]\s*|\s+)" + SECRET_VALUE
)
SQL_IDENTIFIED_BY_RE = re.compile(r"(?i)\bidentified\s+by\s+(?:password\s+)?['\"]([^'\"\s]{3,128})['\"]")
SQL_USER_RE = re.compile(r"(?i)\b(?:create|alter|drop)\s+(?:user|role)\s+(?:if\s+(?:not\s+)?exists\s+)?['\"`]?([A-Za-z_][\w.$-]{1,63})")
DB_CLI_USER_RE = re.compile(r"\b(?:psql|mysql|mysqldump|pg_dump|mongosh|mongo)\b[^\n|;&]*?\s(?:-U|-u|--username[= ]|--user[= ])\s*['\"]?([A-Za-z_][\w.-]{1,63})")
NETRC_RE = re.compile(r"\bmachine\s+\S+\s+login\s+(\S+)\s+password\s+(\S+)")
AS_USER_RE = re.compile(r"(?i)\b(?:logged in as|signed in as|logged on as|log in as|login as|runs as|running as|run as|as user)\s+['\"`]?([a-z_][a-z0-9._-]{2,31})(?![A-Za-z0-9._-])")
HOME_DIR_RE = re.compile(r"(?:/home/|/Users/|[A-Za-z]:\\Users\\)([A-Za-z0-9._-]{2,32})(?=[/\\\s'\"]|$)")
NON_PERSONAL_DIRS = frozenset({"shared", "public", "default", "all users", "guest", "admin", "administrator", "root"})
STRONG_SECRET_RE = re.compile(r"(?=.*\d)|(?=.*[^\w])|(?=.*[a-z].*[A-Z])|(?=.*[A-Z].*[a-z].*[A-Z])")
USERNAME_RE = re.compile(
    r"(?i)(?<![A-Za-z])(?:user(?:[\s_-]?name)?|login|user[\s_-]?id|handle|uid)[\"']?"
    r"(?:\s+(?:is|was)\b\s*|\s*[:=]\s*)" + r"[\"'`]?([A-Za-z0-9][A-Za-z0-9._-]{1,63})[\"'`]?(?![A-Za-z0-9._-])"
)
URL_CREDENTIALS_RE = re.compile(r"[a-z][a-z0-9+.-]*://([^:/\s@]+):([^@\s/]+)@")
CURL_USER_RE = re.compile(r"(?:-u|--user)\s+[\"']?([^:\s\"']+):([^\s\"']+)")
SSH_USER_RE = re.compile(r"\b(?:ssh|scp|sftp)\s+(?:-\S+\s+)*([a-z_][a-z0-9_.-]{0,31})@")
STREET_SUFFIX = (
    "Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Way|Court|Ct|Place|Pl|"
    "Parkway|Pkwy|Terrace|Ter|Circle|Cir|Highway|Hwy|Square|Sq|Trail|Trl|Crescent|Close|Row|"
    "Crossing|Landing|Lodge|Plaza|Alley|Gardens|Grove|Heights|Hill|Ridge|Path|Walk|Loop|Pike"
)
STREET_RE = re.compile(
    r"\b\d{1,6}[A-Za-z]?\s+((?:[NSEW]\.?\s+)?(?:[A-Z][a-z]+|\d+(?:st|nd|rd|th))(?:\s+[A-Z][a-z]+){0,2}\s+(?:"
    + STREET_SUFFIX + r")\b\.?)"
)
PLACEHOLDER_RE = re.compile(r"(?i)^(?:<.*>|\{.*\}|\$\{?.*|\*+|x+|\.+|redacted|hidden|none|null|n/a|tbd|is|was|the|a|an|and|or|for|field|reset|here|required|policy|manager|must|should|will|expired|incorrect|wrong)$")
COMMON_WORDS = frozenset(
    "and or the a an is was are be to of for in on with field must should will can not same as "
    "your my our their his her its this that it name names format reset changed change required "
    "policy manager login password email account granted denied successful failed invalid incorrect "
    "locked blocked disabled enabled active expired dr mr mrs ms prof sir madam".split()
)


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def iban_valid(candidate: str) -> bool:
    s = candidate.replace(" ", "").upper()
    if not (15 <= len(s) <= 34) or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", s):
        return False
    rearranged = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def _cue_before(text: str, start: int, cue: re.Pattern, window: int = 40) -> bool:
    return bool(cue.search(text[max(0, start - window):start]))


def _strip_trailing(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1] in ".,;:!?)]}'\"`":
        end -= 1
    return end


class RuleDetector:
    name = "rules"

    def __init__(self, labels: Iterable[str] | None = None, region: str = "US"):
        self.labels = set(labels) if labels else set(PRIORITY)
        self.region = region

    def detect(self, text: str) -> list[Span]:
        found: list[Span] = []
        add = found.append

        for m in EMAIL_RE.finditer(text):
            add(Span(m.start(), m.end(), "EMAIL", 0.99))

        for m in IPV4_RE.finditer(text):
            before = text[max(0, m.start() - 40):m.start()]
            after = text[m.end():m.end() + 12]
            network = bool(IP_CUE_RE.search(before[-15:]) or IP_STRUCTURE_BEFORE_RE.search(before[-12:])
                           or IP_STRUCTURE_AFTER_RE.match(after))
            octets = [int(x) for x in m.group(0).split(".")]
            # Dotted quads with a small first octet outside the private ranges are, without
            # network context, usually version numbers (2.4.1.7, 7.5.0.10).
            address_like = octets[0] >= 30 or octets[0] == 10 or m.group(0).startswith(("172.", "192.168."))
            if network or (address_like and not VERSION_CUE_RE.search(before)):
                add(Span(m.start(), m.end(), "IPV4", 0.95))

        for m in IBAN_CANDIDATE_RE.finditer(text):
            raw = m.group(0)
            # The greedy match may run into following uppercase tokens; take the longest
            # checksum-valid prefix.
            for cut in range(len(raw), 14, -1):
                if raw[cut - 1] != " " and iban_valid(raw[:cut]):
                    add(Span(m.start(), m.start() + cut, "IBAN", 0.99))
                    break

        for m in CARD_CANDIDATE_RE.finditer(text):
            raw = m.group(0)
            digits = re.sub(r"\D", "", raw)
            if not 13 <= len(digits) <= 19:
                continue
            if IMEI_RE.match(raw) or _cue_before(text, m.start(), IMEI_CUE_RE, 25):
                continue  # IMEIs carry a Luhn check digit too
            if re.match(r"[ -]?\d", text[m.end():m.end() + 2]) or _cue_before(text, m.start(), ID_CUE_RE, 25):
                continue  # part of a longer number, or introduced as an identifier
            groups = tuple(len(g) for g in re.split(r"[ -]", raw))
            if len(groups) > 1 and groups not in CARD_GROUPINGS:
                continue  # separators in a non-card grouping (e.g. 3-7-7 order numbers)
            card_cue = _cue_before(text, m.start(), CARD_CUE_RE)
            if luhn_valid(digits) and (len(digits) >= 14 or card_cue):
                add(Span(m.start(), m.end(), "CREDITCARDNUMBER", 0.97))
            elif card_cue:
                add(Span(m.start(), m.end(), "CREDITCARDNUMBER", 0.7))

        for m in SSN_DASH_RE.finditer(text):
            add(Span(m.start(), m.end(), "SSN", 0.9))
        for m in SSN_OTHER_RE.finditer(text):
            if _cue_before(text, m.start(), SSN_CUE_RE):
                add(Span(m.start(), m.end(), "SSN", 0.85))

        for rx in (CVV_RE, CVV_BEFORE_CUE_RE):
            for m in rx.finditer(text):
                start, end = m.start("value"), m.end("value")
                if CVV_STRONG_CUE_RE.fullmatch(m.group("cue")) or card_context(text, start, end, include_card_words=True):
                    add(Span(start, end, "CREDITCARDCVV", 0.85))

        for m in ACCOUNT_RE.finditer(text):
            value = m.group(1).rstrip(" -")
            if 6 <= len(re.sub(r"\D", "", value)) <= 20:
                add(Span(m.start(1), m.start(1) + len(value), "ACCOUNTNUMBER", 0.8))

        for m in PASSWORD_RE.finditer(text):
            start = m.start("value")
            quoted = start > 0 and text[start - 1] in "\"'`"
            end = m.end("value") if quoted else _strip_trailing(text, start, m.end("value"))
            value = text[start:end]
            if end - start < 3 or PLACEHOLDER_RE.match(value) or value.lower() in COMMON_WORDS:
                continue
            if m.group("kw").lower() == "passcode" and value.isdigit():
                continue  # numeric passcodes (door, locker, meeting) are PINs: outside the scope
            sep = m.group("sep").strip().lower()
            explicit = sep in {":", "=", "is", "was"}  # rather than a bare space or "to"/"of"
            short_kw = m.group("kw").lower() in {"pass", "pw"}
            if (explicit and not (short_kw and sep in {"is", "was"})) or (
                not short_kw and STRONG_SECRET_RE.match(value) and value[0] not in "("
            ):
                add(Span(start, end, "PASSWORD", 0.8 if explicit else 0.6))
        for m in USERNAME_RE.finditer(text):
            start, end = m.start(1), _strip_trailing(text, m.start(1), m.end(1))
            value = text[start:end]
            if value.lower() not in COMMON_WORDS and not PLACEHOLDER_RE.match(value):
                add(Span(start, end, "USERNAME", 0.75))
        for m in URL_CREDENTIALS_RE.finditer(text):
            add(Span(m.start(1), m.end(1), "USERNAME", 0.9))
            add(Span(m.start(2), m.end(2), "PASSWORD", 0.9))
        for m in CURL_USER_RE.finditer(text):
            add(Span(m.start(1), m.end(1), "USERNAME", 0.9))
            add(Span(m.start(2), m.end(2), "PASSWORD", 0.9))
        for m in SSH_USER_RE.finditer(text):
            add(Span(m.start(1), m.end(1), "USERNAME", 0.85))
        for m in SQL_IDENTIFIED_BY_RE.finditer(text):
            add(Span(m.start(1), m.end(1), "PASSWORD", 0.9))
        for rx in (SQL_USER_RE, DB_CLI_USER_RE, AS_USER_RE):
            for m in rx.finditer(text):
                value = m.group(1)
                if value.lower() not in COMMON_WORDS and value.lower() not in NON_PERSONAL_DIRS:
                    add(Span(m.start(1), _strip_trailing(text, m.start(1), m.end(1)), "USERNAME", 0.8))
        for m in HOME_DIR_RE.finditer(text):
            if m.group(1).lower() not in NON_PERSONAL_DIRS:
                add(Span(m.start(1), m.end(1), "USERNAME", 0.8))
        for m in NETRC_RE.finditer(text):
            add(Span(m.start(1), m.end(1), "USERNAME", 0.9))
            add(Span(m.start(2), m.end(2), "PASSWORD", 0.9))

        for match in phonenumbers.PhoneNumberMatcher(text, self.region, leniency=phonenumbers.Leniency.VALID):
            before = text[match.start - 1] if match.start else " "
            after = text[match.end] if match.end < len(text) else " "
            if before.isalnum() or before in "./[,-" or after.isalnum() or after in "]/":
                continue  # inside a hex string, version, coordinate pair, or other token
            if len(re.sub(r"\D", "", match.raw_string)) < 7:
                continue
            if _cue_before(text, match.start, ID_CUE_RE, 25):
                continue  # "tracking 2899564846", "bridge 182 6291 3294": identifiers, not phones
            if any(q.start() < match.end and match.start < q.end() for q in DOTTED_QUAD_RE.finditer(text)):
                continue  # digits of an IP address or version number
            add(Span(match.start, match.end, "PHONENUMBER", 0.8))

        for m in STREET_RE.finditer(text):
            add(Span(m.start(1), _strip_trailing(text, m.start(1), m.end(1)), "STREET", 0.7))

        return resolve_overlaps([s for s in found if s.label in self.labels])

    def detect_batch(self, texts: list[str]) -> list[list[Span]]:
        return [self.detect(t) for t in texts]


def resolve_overlaps(spans: list[Span], priority: dict[str, int] = PRIORITY) -> list[Span]:
    """Keep the highest-priority (then longest) span among overlapping candidates."""
    ranked = sorted(spans, key=lambda s: (-priority.get(s.label, 0), -(s.end - s.start), s.start))
    kept: list[Span] = []
    for span in ranked:
        if not any(span.overlaps(k) for k in kept):
            kept.append(span)
    return sorted(kept)
