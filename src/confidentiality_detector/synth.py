"""Round-2 synthetic training data: hard negatives (experiment A) and difficult positives (B).

Templates are grouped into *families* (value group x document frame, e.g. tracking/chat,
tracking/email). Within every value group with two or more families, one whole family is
held out: it is never used for training and only produces the `synth_*_heldout` evaluation
sets, which therefore measure generalisation to unseen generation patterns.

Slot syntax inside a template: {n:TYPE} out-of-scope look-alike (negative span, trained as O),
{p:TYPE} target entity (gold span), {x:TYPE} unannotated filler. Person-dependent slots in
one document refer to the same generated person. Every generated value is fictional.

Annotation rules enforced at generation time (and re-checked by quality.validate_synthetic):
  * CREDITCARDCVV only appears with contextual evidence (labels.cvv_has_evidence);
  * a person name never appears unannotated; company/product names are negatives;
  * no API keys, tokens, meeting passcodes or OTPs (out of scope; not taught either way);
  * public-figure names are never used as negatives (final person-name policy).
"""

from __future__ import annotations

import hashlib
import random
import re
import string
import uuid
from dataclasses import dataclass, field

from .documents import Document, Span
from .labels import TARGET_SET, cvv_has_evidence
from .perturb import iban_complete, luhn_complete

GENERATOR_VERSION = "round2-v1"

FIRST_NAMES_C = """Aino Bartholomew Cosima Desmond Elif Florentin Gwendolyn Hamza Isolde Jovan Kaito Liesel Malachi
Noor Orsolya Percival Quilla Rosalind Sigrun Tadeo Ulla Vasco Wilhelmina Xanthe Yannick Zuzana Amara Bastien
Calla Dov Eero Fiorella Gideon Hester Imre Juniper Kasimir Linnea Mirko Nadia Oskar Pilar Radu Saskia Teodor
Una Vidar Wren Yara Zeno Anouar Beatrix Ciaran Dalia Emeric Freya Gaspard Hilde Ilario Jasna Kiran Leocadia""".split()
LAST_NAMES_C = """Abernethy Bjornstad Castellucci Dragomir Esterhazy Falkenrath Grimaldi Holloway Ilyushin Jaroszewski
Kettering Lindgren Marchetti Novakovic Oyelowo Pendergast Quarshie Rasmussen Sandoval-Reyes Thorvaldsen Uchida
Vashchenko Whitlock Yamaguchi Zelenko Ashdown Brightman Calloway Dunleavy Eckhardt Fairbanks Galbraith Hartigan
Ivanisevic Jablonski Kowalewski Lachance Mortensen Northcott Ostrowski Pemberton Quinlan Radcliffe Strassburg
Tennant Underhill Vandeventer Wakefield Yardley Zimmerli""".split()
STREET_NAMES = """Alder Bellflower Cobblestone Driftwood Elmhurst Foxglove Granary Heathcote Ironwood Juniperberry Kingfisher
Lantern Millbrook Nettlefield Orchardview Pinecrest Quayside Ravenscroft Saltmarsh Thistledown Upland Valewood
Willowmere Yarrow""".split()
STREET_SUFFIXES = ["Street", "Road", "Lane", "Avenue", "Close", "Drive", "Way", "Court", "Terrace", "Place", "Crescent", "Row"]
DOMAINS = ["meridian-labs.example", "quayside-logistics.example", "harrowgate.example", "lumenfield.example",
           "corvid-analytics.example", "tidewater-health.example", "northgate-finance.example"]
COMPANIES = ["Northwind Traders", "Contoso Ltd", "Fabrikam Inc.", "Tailspin Toys", "Wingtip Partners", "Litware Inc.",
             "Adatum Corporation", "Proseware GmbH", "Lucerne Publishing", "Trey Research"]
PRODUCTS = ["Grafana", "Jenkins", "Kubernetes", "Postgres", "Terraform", "Kafka", "Airflow", "Redis", "Nginx", "Prometheus"]
PASSWORD_WORDS = ["harbor", "copper", "lantern", "meadow", "falcon", "quartz", "violet", "ember", "glacier", "cobalt",
                  "saffron", "tundra", "orbit", "maple", "willow", "comet"]


def _digits(rng, n):
    return "".join(rng.choice(string.digits) for _ in range(n))


def _alnum(rng, n, upper=True):
    pool = (string.ascii_uppercase if upper else string.ascii_lowercase) + string.digits
    return "".join(rng.choice(pool) for _ in range(n))


def _group(s, size, sep=" "):
    return sep.join(s[i:i + size] for i in range(0, len(s), size))


@dataclass
class Person:
    first: str
    last: str


@dataclass
class Ctx:
    rng: random.Random
    names: tuple[list, list]
    person: Person | None = None
    extra: dict = field(default_factory=dict)

    def who(self) -> Person:
        if self.person is None:
            self.person = Person(self.rng.choice(self.names[0]), self.rng.choice(self.names[1]))
        return self.person


def _ascii(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


# ---------------------------------------------------------------- value generators
def _ean13(rng):
    body = _digits(rng, 12)
    check = (10 - sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body)) % 10) % 10
    return body + str(check)


def _aba(rng):
    while True:
        d = _digits(rng, 8)
        w = [3, 7, 1] * 3
        for c in range(10):
            n = d + str(c)
            if sum(int(x) * y for x, y in zip(n, w)) % 10 == 0:
                return n


def _ipv4_shaped_version(rng):
    return ".".join(str(rng.randint(0, 20)) for _ in range(4))


def _password(rng):
    style = rng.randrange(5)
    if style == 0:
        return "".join(rng.choice(string.ascii_letters + string.digits + "!#$%&*?@") for _ in range(rng.randint(10, 16)))
    if style == 1:
        return f"{rng.choice(PASSWORD_WORDS).capitalize()}{rng.randint(10, 9999)}{rng.choice('!#$%&*?')}"
    if style == 2:
        return "-".join(rng.sample(PASSWORD_WORDS, 3)) + str(rng.randint(1, 99))
    if style == 3:
        leet = str.maketrans({"a": "@", "o": "0", "e": "3", "i": "1", "s": "$"})
        return rng.choice(PASSWORD_WORDS).translate(leet) + rng.choice(["!", "#", "_"]) + _digits(rng, rng.randint(2, 4))
    return _alnum(rng, 4, upper=False) + rng.choice("!#%") + _alnum(rng, 4) + rng.choice("-_.") + _digits(rng, 2)


def _username(ctx):
    rng, p = ctx.rng, ctx.who()
    f, l = _ascii(p.first), _ascii(p.last)
    return rng.choice([f"{f[0]}{l}", f"{f}.{l}", f"{l}_{f[0]}", f"{f}{rng.randint(1, 99)}", f"{f[0]}{l[:5]}",
                       f"dev-{l}", f"{f}_{l[:3]}{rng.randint(1, 9)}"])


def _service_user(rng):
    return rng.choice(["svc_", "app_", "etl_", "ci-", "deploy-", "report_", "sync-"]) + rng.choice(
        ["orders", "billing", "ingest", "reader", "runner", "backup", "export", "metrics", "crm"]) + rng.choice(["", "", str(rng.randint(1, 9))])


def _card(rng, sep):
    prefix, length = rng.choice([("4", 16), ("51", 16), ("52", 16), ("55", 16), ("6011", 16), ("37", 15)])
    num = luhn_complete(prefix, length, rng)
    if length == 15:
        return f"{num[:4]}{sep}{num[4:10]}{sep}{num[10:]}" if sep is not None else num
    return _group(num, 4, sep) if sep is not None else num


def _iban(rng, grouped):
    country, bban = rng.choice([("DE", _digits(rng, 18)), ("GB", rng.choice(["NWBK", "BARC", "LOYD"]) + _digits(rng, 14)),
                                ("FR", _digits(rng, 23)), ("NL", rng.choice(["ABNA", "INGB", "RABO"]) + _digits(rng, 10)),
                                ("ES", _digits(rng, 20)), ("IT", rng.choice(string.ascii_uppercase) + _digits(rng, 22)),
                                ("BE", _digits(rng, 12)), ("CH", _digits(rng, 17))])
    iban = iban_complete(country, bban)
    return _group(iban, 4) if grouped else iban


def _phone(rng):
    return rng.choice([f"+1 ({rng.randint(201, 989)}) 555-01{_digits(rng, 2)}", f"{rng.randint(201, 989)}-555-01{_digits(rng, 2)}",
                       f"+44 7700 900{_digits(rng, 3)}", f"+49 30 5550 {_digits(rng, 4)}", f"+33 1 55 50 {_digits(rng, 2)} {_digits(rng, 2)}",
                       f"{rng.randint(201, 989)}.555.01{_digits(rng, 2)}", f"+61 2 5550 {_digits(rng, 4)}"])


def _ssn(rng):
    a = rng.choice([n for n in range(1, 900) if n != 666])
    return f"{a:03d}-{rng.randint(1, 99):02d}-{rng.randint(1, 9999):04d}"


def _account(rng):
    return rng.choice([_digits(rng, rng.randint(9, 14)), f"{_digits(rng, 4)}-{_digits(rng, 4)}-{_digits(rng, 4)}",
                       f"{_digits(rng, 3)}-{_digits(rng, 6)}-{_digits(rng, 2)}", f"{_digits(rng, 4)} {_digits(rng, 4)} {_digits(rng, 4)}"])


def _ipv4(rng):
    return rng.choice([f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
                       f"172.{rng.randint(16, 31)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
                       f"192.168.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
                       f"{rng.randint(11, 223)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"])


def _street(rng, lower=False):
    s = f"{rng.choice(STREET_NAMES)} {rng.choice(STREET_SUFFIXES)}"
    return s.lower() if lower else s


GEN = {
    # out-of-scope look-alikes (negatives)
    "TRACKING": lambda c: c.rng.choice([f"1Z{_alnum(c.rng, 6)}{_digits(c.rng, 10)}", _group(_digits(c.rng, 12), 4),
                                         _group("9400" + _digits(c.rng, 18), 4), _digits(c.rng, 10)]),
    "ORDERID": lambda c: c.rng.choice([f"{_digits(c.rng, 3)}-{_digits(c.rng, 7)}-{_digits(c.rng, 7)}", f"SO-{_digits(c.rng, 5)}",
                                        f"A-{_digits(c.rng, 5)}-{_digits(c.rng, 2)}", f"PO-2024-{_digits(c.rng, 5)}", f"#{_digits(c.rng, 9)}"]),
    "MEETINGID": lambda c: c.rng.choice([f"{_digits(c.rng, 3)} {_digits(c.rng, 4)} {_digits(c.rng, 4)}",
                                          f"{_digits(c.rng, 3)} {_digits(c.rng, 3)} {_digits(c.rng, 3)} {_digits(c.rng, 3)}",
                                          f"{_digits(c.rng, 3)}-{_digits(c.rng, 4)}-{_digits(c.rng, 4)}"]),
    "ERRORCODE": lambda c: c.rng.choice([f"0x8{_alnum(c.rng, 7, upper=False).replace('g', 'a')}", f"E-{_digits(c.rng, 4)}",
                                          f"ERR_{c.rng.choice(['CONN', 'AUTH', 'SYNC', 'QUOTA'])}_{_digits(c.rng, 4)}",
                                          f"ORA-{_digits(c.rng, 5)}", f"SYNC-{_digits(c.rng, 4)}", f"STOP 0x000000{_alnum(c.rng, 2)}"]),
    "VERSION": lambda c: c.rng.choice([f"{c.rng.randint(0, 30)}.{c.rng.randint(0, 40)}.{c.rng.randint(0, 99)}",
                                        f"v{c.rng.randint(1, 9)}.{c.rng.randint(0, 20)}.{c.rng.randint(0, 20)}",
                                        f"10.0.{c.rng.randint(17000, 26000)}.{c.rng.randint(100, 4999)}",
                                        _ipv4_shaped_version(c.rng), f"{c.rng.randint(1, 9)}.{c.rng.randint(0, 9)}.0-rc.{c.rng.randint(1, 5)}"]),
    "MATH": lambda c: c.rng.choice([f"{c.rng.randint(100, 9999)} * {c.rng.randint(10, 9999)} - {c.rng.randint(100, 9999)}",
                                     f"{c.rng.randint(2, 9)}x + {c.rng.randint(100, 999)} = {c.rng.randint(1000, 9999)}",
                                     f"({c.rng.randint(100, 999)} + {c.rng.randint(100, 999)}) / {c.rng.randint(2, 12)}"]),
    "INVOICE": lambda c: c.rng.choice([f"INV-{_digits(c.rng, 5)}-{c.rng.choice('ABCD')}", f"INV-2024-{_digits(c.rng, 4)}", f"#INV{_digits(c.rng, 7)}"]),
    "TICKET": lambda c: c.rng.choice([f"{c.rng.choice(['OPS', 'PLAT', 'SEC', 'FIN', 'HR'])}-{_digits(c.rng, 5)}",
                                       f"INC{_digits(c.rng, 7)}", f"CS-2024-{_digits(c.rng, 6)}"]),
    "SKU": lambda c: c.rng.choice([_ean13(c.rng), f"{_alnum(c.rng, 3)}-{_digits(c.rng, 4)}", f"MX-{_digits(c.rng, 4)}-{c.rng.choice('ABC')}"]),
    "SERIAL": lambda c: c.rng.choice([f"SN-{_alnum(c.rng, 4)}-{_alnum(c.rng, 4)}-{_digits(c.rng, 2)}", _alnum(c.rng, 12),
                                       f"IT-{_digits(c.rng, 6)}", f"LOT {_digits(c.rng, 2)}{c.rng.choice('ABC')}{_digits(c.rng, 4)}"]),
    "BOOKING": lambda c: c.rng.choice([_alnum(c.rng, 6), f"{c.rng.choice(['LH', 'BA', 'AF', 'KL', 'UA'])} {c.rng.randint(100, 9999)}"]),
    "UUID": lambda c: str(uuid.UUID(int=c.rng.getrandbits(128), version=4)),
    "HASH": lambda c: "".join(c.rng.choice("0123456789abcdef") for _ in range(c.rng.choice([7, 12, 40]))),
    "COMPANYID": lambda c: c.rng.choice([f"{_digits(c.rng, 2)}-{_digits(c.rng, 3)}-{_digits(c.rng, 4)}", f"{_digits(c.rng, 2)}-{_digits(c.rng, 7)}",
                                          f"DE{_digits(c.rng, 9)}", _digits(c.rng, 9)]),
    "ROUTING": lambda c: _aba(c.rng),
    "BIC": lambda c: c.rng.choice(["DEUTDEFF", "NWBKGB2L", "BNPAFRPP", "INGBNL2A", "COBADEFF"]) + c.rng.choice(["", "XXX", _digits(c.rng, 3)]),
    "PINCODE": lambda c: c.rng.choice([_digits(c.rng, 4), "-".join(_digits(c.rng, 1) for _ in range(4)), _digits(c.rng, 6)]),
    "SHORTNUM": lambda c: str(c.rng.choice([c.rng.randint(2, 99), c.rng.randint(100, 999), c.rng.randint(1000, 9999)])),
    "COMPANY": lambda c: c.rng.choice(COMPANIES),
    "PRODUCT": lambda c: c.rng.choice(PRODUCTS),
    # unannotated filler
    "DATE": lambda c: c.rng.choice([f"2024-{c.rng.randint(1, 12):02d}-{c.rng.randint(1, 28):02d}", f"{c.rng.randint(1, 28)} March", "next Tuesday", f"{c.rng.randint(1, 12):02d}/{c.rng.randint(1, 28):02d}"]),
    "TIME": lambda c: f"{c.rng.randint(0, 23):02d}:{c.rng.randint(0, 59):02d}",
    "AMOUNT": lambda c: c.rng.choice([f"${c.rng.randint(10, 99999):,}.{_digits(c.rng, 2)}", f"EUR {c.rng.randint(10, 9999):,}", f"{c.rng.randint(1, 99)}%"]),
    "CITY": lambda c: c.rng.choice(["Rotterdam", "Leeds", "Lyon", "Porto", "Gdansk", "Tampere", "Graz", "Cork", "Bologna"]),
    "EXPIRY": lambda c: f"{c.rng.randint(1, 12):02d}/{c.rng.randint(26, 31)}",
    # targets
    "FIRST": lambda c: c.who().first,
    "LAST": lambda c: c.who().last,
    "first": lambda c: c.who().first.lower(),
    "last": lambda c: c.who().last.lower(),
    "EMAIL": lambda c: f"{c.rng.choice([_ascii(c.who().first) + '.' + _ascii(c.who().last), _ascii(c.who().first)[0] + _ascii(c.who().last), _ascii(c.who().last) + '+' + c.rng.choice(['billing', 'ops', 'hr'])])}@{c.rng.choice(DOMAINS)}",
    "USERNAME": _username,
    "SVCUSER": lambda c: _service_user(c.rng),
    "PASSWORD": lambda c: _password(c.rng),
    "PHONE": lambda c: _phone(c.rng),
    "SSN": lambda c: _ssn(c.rng),
    "CARD": lambda c: _card(c.rng, c.rng.choice([" ", "-", None])),
    "CVV3": lambda c: _digits(c.rng, 3),
    "CVV4": lambda c: _digits(c.rng, 4),
    "IBAN": lambda c: _iban(c.rng, grouped=c.rng.random() < 0.6),
    "ACCOUNT": lambda c: _account(c.rng),
    "STREET": lambda c: _street(c.rng),
    "street": lambda c: _street(c.rng, lower=True),
    "IPV4": lambda c: _ipv4(c.rng),
    "HOUSENO": lambda c: str(c.rng.randint(1, 240)),
}
TARGET_OF = {"FIRST": "FIRSTNAME", "first": "FIRSTNAME", "LAST": "LASTNAME", "last": "LASTNAME", "EMAIL": "EMAIL",
             "USERNAME": "USERNAME", "SVCUSER": "USERNAME", "PASSWORD": "PASSWORD", "PHONE": "PHONENUMBER", "SSN": "SSN",
             "CARD": "CREDITCARDNUMBER", "CVV3": "CREDITCARDCVV", "CVV4": "CREDITCARDCVV", "IBAN": "IBAN",
             "ACCOUNT": "ACCOUNTNUMBER", "STREET": "STREET", "street": "STREET", "IPV4": "IPV4"}
assert set(TARGET_OF.values()) <= TARGET_SET

# ---------------------------------------------------------------- template families
# family id -> templates. Family ids are "<kind>.<value group>.<frame>".
FAMILIES: dict[str, list[str]] = {
    # ---- experiment A: hard negatives (ALLOW, or mixed with one clear target) ----
    "neg.tracking.chat": [
        "the carrier page shows {n:TRACKING} as awaiting pickup for three days, what do I tell the client?",
        "is {n:TRACKING} the kind of number UPS uses or is it a postal service one?",
        "parcel {n:TRACKING} bounced back to the {x:CITY} depot, can you write a note asking the courier why",
        "Please explain the scan events for shipment {n:TRACKING} in plain words.",
        "customer swears {n:TRACKING} was delivered to the wrong building, how do we open a claim?",
    ],
    "neg.tracking.email": [
        "Hello all,\n\nConsignment {n:TRACKING} (PO {n:ORDERID}) missed its delivery window. Please prepare a holding reply for the account owner.\n\nRegards",
        "Subject: re-routing request\n\nWe need {n:TRACKING} re-routed to the {x:CITY} warehouse before {x:DATE}. Draft the request to the carrier.",
        "Team, two consignments ({n:TRACKING}, {n:TRACKING}) show customs holds. Summarise what documents are usually missing.",
    ],
    "neg.tracking.log": [
        "[{x:TIME}] carrier-sync updated {n:TRACKING} status=IN_TRANSIT hub={x:CITY}\n[{x:TIME}] carrier-sync updated {n:TRACKING} status=DELIVERED\nwhy did the second update arrive before the first?",
        "webhook payload rejected: shipment={n:TRACKING} event=OUT_FOR_DELIVERY reason=duplicate\nhow do I make the handler idempotent?",
    ],
    "neg.order.chat": [
        "the refund for {n:ORDERID} went out twice, write finance a short note to claw one back",
        "a customer says {n:ORDERID} came with the wrong colour, draft an exchange offer",
        "should references like {n:ORDERID} and {n:ORDERID} be padded to the same width in the export?",
        "Can you explain why order {n:ORDERID} is stuck in 'pending fulfilment'?",
        "we cancelled {n:ORDERID} but the warehouse still picked it; write an escalation",
    ],
    "neg.order.json": [
        '{{"order_id": "{n:ORDERID}", "quantity": {n:SHORTNUM}, "sku": "{n:SKU}", "total": "{x:AMOUNT}"}}\nconvert this to a TypeScript type',
        '[{{"order": "{n:ORDERID}", "status": "open"}}, {{"order": "{n:ORDERID}", "status": "shipped"}}]\nhow many orders are still open?',
        '{{"po": "{n:ORDERID}", "lines": [{{"sku": "{n:SKU}", "qty": {n:SHORTNUM}}}]}}\nwrite a pydantic model for this',
    ],
    "neg.meeting.invite": [
        "Agenda for {x:DATE}, {x:TIME}: budget review. Conference ID {n:MEETINGID}. Make this look tidy.",
        "Calendar text needed: architecture review, bridge {n:MEETINGID}, room booked on the 3rd floor.",
        "Recurring standup moved to {x:TIME}; the bridge number stays {n:MEETINGID}. Rewrite the announcement.",
    ],
    "neg.meeting.chat": [
        "the bridge {n:MEETINGID} says host has not joined, should I wait or ping someone",
        "which tool uses ids shaped like {n:MEETINGID}? zoom or teams?",
        "put {n:MEETINGID} at the top of the minutes so people can rejoin",
    ],
    "neg.error.chat": [
        "our installer exits with {n:ERRORCODE} on some laptops, any idea why?",
        "the job died with {n:ERRORCODE} after {n:SHORTNUM} retries, how do I debug that?",
        "what's the difference between {n:ERRORCODE} and {n:ERRORCODE} in our runbook?",
        "users report {n:ERRORCODE} when exporting large reports — write a status page note",
    ],
    "neg.error.log": [
        "{x:DATE} {x:TIME} ERROR payment-worker request {n:UUID} failed: {n:ERRORCODE} (attempt {n:SHORTNUM})\nexplain this error",
        "[{x:TIME}] WARN sync: cursor stale ({n:ERRORCODE}), retrying in {n:SHORTNUM} ms\n[{x:TIME}] INFO sync: resumed batch {n:SHORTNUM}\nis the retry policy ok?",
        "trace {n:HASH}: upstream returned {n:ERRORCODE} after {n:SHORTNUM} ms\nwhat should the timeout be?",
    ],
    "neg.version.chat": [
        "after updating the dock driver from {n:VERSION} to {n:VERSION} the second monitor flickers",
        "does library {n:VERSION} still support the old auth flow, or do we need {n:VERSION}?",
        "is it risky to stay on {n:VERSION} until the end of the quarter?",
        "the agent reports build {n:VERSION} but the console expects {n:VERSION}",
    ],
    "neg.version.notes": [
        "Release {n:VERSION}\n- fixes crash on startup\n- requires server {n:VERSION} or newer\n- build {n:VERSION}\nmake these notes friendlier",
        "Changelog: {n:VERSION} adds offline mode; {n:VERSION} removes the legacy export API. Summarise for customers.",
        "Compatibility matrix\nclient {n:VERSION} -> server {n:VERSION}\nclient {n:VERSION} -> server {n:VERSION}\nturn this into a sentence",
    ],
    "neg.math.chat": [
        "work out {n:MATH} for me and show each step",
        "solve {n:MATH} and explain it like I'm 12",
        "if we ship {n:SHORTNUM} units a day for {n:SHORTNUM} days, what's the total?",
        "check my homework: {n:MATH}",
    ],
    "neg.invoice.email": [
        "Hi,\n\nPayment for {n:INVOICE} is now {n:SHORTNUM} days late. Could you draft a friendly but firm follow-up?",
        "Please match invoice {n:INVOICE} to purchase order {n:ORDERID} and tell me if the amounts ({x:AMOUNT}) agree.",
        "The client disputes line 3 of {n:INVOICE}. Write a reply asking which item they mean.",
    ],
    "neg.ticket.chat": [
        "can you merge {n:TICKET} into {n:TICKET}? they describe the same outage",
        "the vendor closed {n:TICKET} without fixing anything, help me push back politely",
        "write a one-line status for {n:TICKET} for the incident channel",
    ],
    "neg.ticket.csv": [
        "ticket,priority,age_days\n{n:TICKET},P2,{n:SHORTNUM}\n{n:TICKET},P1,{n:SHORTNUM}\n{n:TICKET},P3,{n:SHORTNUM}\nwhich tickets breach the SLA?",
        "id;component;owner_team\n{n:TICKET};billing;payments\n{n:TICKET};search;discovery\ngroup these by team",
    ],
    "neg.product.chat": [
        "is {n:SKU} a valid EAN or did someone mistype it at the stockroom?",
        "the warranty lookup can't find unit {n:SERIAL}, what else can I try?",
        "write SQL that buckets items like {n:SKU} and {n:SKU} by prefix",
        "label printer outputs {n:SKU} under the barcode, is that the GTIN?",
    ],
    "neg.travel.chat": [
        "airline ref {n:BOOKING} — can I change the date without a fee usually?",
        "write a reminder: {n:BOOKING} departs {x:TIME} from {x:CITY}, bring the conference badge",
        "is {n:BOOKING} a flight number or a booking code?",
    ],
    "neg.ids.chat": [
        "what does the version nibble in {n:UUID} tell me?",
        "how do I cherry-pick {n:HASH} onto the release branch?",
        "the trace id {n:UUID} appears in two services, does that mean a retry?",
        "should we store ids like {n:UUID} as text or as a native uuid column?",
    ],
    "neg.companyid.form": [
        "Supplier registration\nCompany number: {n:COMPANYID}\nVAT: {n:COMPANYID}\nWhich box takes which?",
        "the tender portal rejects our registration id {n:COMPANYID}, does it need a country prefix?",
    ],
    "neg.bank-ref.chat": [
        "which bank does ABA {n:ROUTING} belong to? just the institution name",
        "does {n:BIC} identify a specific branch?",
        "explain the difference between a BIC like {n:BIC} and a routing number like {n:ROUTING}",
    ],
    "neg.pin.policy": [
        "make a notice: the stationery cupboard code is {n:PINCODE}, keep the door shut",
        "Policy draft: badge door codes such as {n:PINCODE} change every quarter. Make it sound official.",
        "the gym locker uses {n:PINCODE}; write a reminder not to leave valuables inside",
    ],
    "neg.short.chat": [
        "the workshop is in room {n:SHORTNUM}, building B — write directions from reception",
        "the manual has {n:SHORTNUM} pages, propose a reading plan for new hires",
        "we need {n:SHORTNUM} chairs and {n:SHORTNUM} name badges for the offsite",
        "service listens on port {n:SHORTNUM}; how do I check it from the bastion?",
        "line {n:SHORTNUM} of the script throws an index error, what's wrong?",
    ],
    "neg.company.chat": [
        "compare the latest results of {n:COMPANY} and {n:COMPANY} in two sentences",
        "our pipeline runs on {n:PRODUCT} with alerts in {n:PRODUCT}; draft an architecture blurb",
        "write a short case study about moving from {n:PRODUCT} to {n:PRODUCT}",
        "{n:COMPANY} asked for a reference customer, write a polite reply",
    ],
    # mixed documents: look-alikes next to exactly one clearly sensitive value
    "mix.order-email.email": [
        "The confirmation for {n:ORDERID} bounced; resend it to {p:EMAIL} and mention tracking {n:TRACKING}.",
        "Accounts payable asked that {n:INVOICE} be emailed to {p:EMAIL} instead of the old inbox.",
    ],
    "mix.version-ip.log": [
        "[{x:TIME}] deploy {n:VERSION} -> host {p:IPV4} ok (build {n:SHORTNUM})",
        "rolled back {n:VERSION} on {p:IPV4} after health checks failed, write the incident summary",
    ],
    "mix.meeting-name.chat": [
        "bridge {n:MEETINGID}: {p:FIRST} is presenting the forecast, draft the agenda",
        "ticket {n:TICKET}: {p:FIRST} {p:LAST} wants an update by {x:DATE}",
    ],
    # ---- experiment B: difficult positives ----
    "pos.name-lower.chat": [
        "remind {p:first} to send the slides before noon",
        "{p:first} and i swapped shifts, update the rota",
        "forward this to {p:first} {p:last} in procurement please",
        "did {p:first} sign off on the budget yet?",
        "cheers,\n{p:first}",
        "{p:first} {p:last} is out sick, who covers the review?",
    ],
    "pos.name-struct.sql": [
        "INSERT INTO staff (given_name, family_name, mail) VALUES ('{p:FIRST}', '{p:LAST}', '{p:EMAIL}');\nwhy does this fail on the unique index?",
        "UPDATE contacts SET last_name = '{p:LAST}' WHERE first_name = '{p:FIRST}';\nis this safe without a primary key?",
        "SELECT * FROM users WHERE full_name = '{p:FIRST} {p:LAST}';\nhow do I make this case-insensitive?",
    ],
    "pos.name-struct.csv": [
        "emp_id,given,family,mobile\n{n:SHORTNUM},{p:FIRST},{p:LAST},{p:PHONE}\nadd a header row comment",
        "name;team;start\n{p:FIRST} {p:LAST};platform;{x:DATE}\nturn this into a table",
    ],
    "pos.name-struct.json": [
        '{{"customer": {{"first_name": "{p:FIRST}", "last_name": "{p:LAST}", "email": "{p:EMAIL}"}}}}\nmask the personal fields',
        '{{"owner": "{p:FIRST} {p:LAST}", "ticket": "{n:TICKET}"}}\nwrite a jq filter for the owner',
        '{{"assignee": {{"name": "{p:FIRST} {p:LAST}"}}, "version": "{n:VERSION}"}}\nflatten this object',
    ],
    "pos.name-header.email": [
        "Sender: {p:FIRST} {p:LAST} <{p:EMAIL}>\nRe: onboarding checklist\nwrite a short reply",
        "On {x:DATE}, {p:FIRST} {p:LAST} wrote:\n> can we move the review?\nreply that thursday works",
    ],
    "pos.username.path": [
        "a backup job writes to /home/{p:USERNAME}/exports and fills the disk, how do I move it?",
        "the script fails on C:\\Users\\{p:USERNAME}\\AppData\\Local\\cache with access denied",
        "why does /Users/{p:USERNAME}/Library/Logs grow so fast?",
    ],
    "pos.username.cli": [
        "ssh {p:USERNAME}@{p:IPV4} hangs at key exchange",
        "mysql -u {p:SVCUSER} -h db.internal reports access denied after the migration",
        "the systemd unit runs as {p:SVCUSER}; how do I give it read access to /srv/data?",
    ],
    "pos.username.chat": [
        "signed in as {p:USERNAME} yet the old permissions still apply, is it cached?",
        "ping @{p:USERNAME} about the flaky test",
        "the audit shows {p:USERNAME} exported the report twice, is that normal?",
    ],
    "pos.username.log": [
        "{x:DATE} {x:TIME} sshd: Accepted publickey for {p:USERNAME} from {p:IPV4}\nis this login expected?",
        "audit: user={p:USERNAME} action=export rows={n:SHORTNUM}\nflag anything unusual",
    ],
    "pos.password.json": [
        '{{"username": "{p:SVCUSER}", "password": "{p:PASSWORD}"}}\nwhy does the API return 401?',
        '{{"db": {{"user": "{p:USERNAME}", "password": "{p:PASSWORD}", "host": "{p:IPV4}"}}}}\nconvert to YAML',
    ],
    "pos.password.yaml": [
        "mailer:\n  user: {p:SVCUSER}\n  password: '{p:PASSWORD}'\n  port: 587\ndoes this need TLS settings?",
        "datasource:\n  url: jdbc:postgresql://db.internal/app\n  username: {p:SVCUSER}\n  password: {p:PASSWORD}\nis this config valid?",
    ],
    "pos.password.sql": [
        "CREATE ROLE {p:SVCUSER} LOGIN PASSWORD '{p:PASSWORD}';\nwhat else does it need to read the views?",
        "SET PASSWORD FOR '{p:SVCUSER}'@'localhost' = '{p:PASSWORD}'; is this deprecated in MySQL 8?",
    ],
    "pos.password.connstring": [
        "Data Source={p:IPV4};Initial Catalog=sales;User ID={p:SVCUSER};Password={p:PASSWORD}; works locally but not in the container",
        "amqp://{p:SVCUSER}:{p:PASSWORD}@mq.internal:5672/ refuses connections since the upgrade",
    ],
    "pos.password.env": [
        "APP_DB_USER={p:SVCUSER}\nAPP_DB_PASS={p:PASSWORD}\nhow do I load these in a systemd unit?",
        "set REDIS_PASSWORD={p:PASSWORD} in the shell but the client still says NOAUTH",
    ],
    "pos.password.chat": [
        "the shared mailbox password is {p:PASSWORD}, can you add it to the onboarding note? (yes I know)",
        "reset my account and it gave me {p:PASSWORD} as the temporary password, is that secure enough?",
        "the guest wifi passphrase is {p:PASSWORD}; write the welcome card",
    ],
    "pos.cvv.form": [
        "Payment form\nCard: {p:CARD}\nValid thru: {x:EXPIRY}\nCVC: {p:CVV3}\nwhich field is failing validation?",
        "pay with {p:CARD}, expires {x:EXPIRY}, security code {p:CVV3} — the gateway says invalid",
    ],
    "pos.cvv.json": [
        '{{"pan": "{p:CARD}", "expiry": "{x:EXPIRY}", "cvc": "{p:CVV3}"}}\nwhich of these must never be logged?',
        '{{"card": {{"number": "{p:CARD}", "security_code": "{p:CVV3}"}}}}\nwrite a JSON schema for this',
    ],
    "pos.cvv.chat": [
        "my amex card verification code is {p:CVV4}, does the form want all four?",
        "typed cvc {p:CVV3} and still get declined",
        "the number printed on the back of my card is {p:CVV3}, is that the one they want?",
    ],
    "pos.bank.chat": [
        "send the refund to {p:IBAN}, that's my new account",
        "my account number {p:ACCOUNT} was closed, where do salaries go now?",
        "transfer the reimbursement to account {p:ACCOUNT} at the savings bank",
    ],
    "pos.bank.form": [
        "Beneficiary: {x:CITY} Trading Ltd\nIBAN: {p:IBAN}\nReference: {n:INVOICE}",
        "Account number: {p:ACCOUNT}\nSort code: 20-20-15\nIs this the right format for the payroll form?",
    ],
    "pos.contact.chat": [
        "reach me on {p:PHONE} while I'm travelling",
        "please cc {p:EMAIL} on the contract thread",
        "new address is {x:HOUSENO} {p:street}, flat 2 — update the HR record",
        "courier should go to {x:HOUSENO} {p:STREET}, {x:CITY}, back entrance",
    ],
    "pos.ssn.form": [
        "Employee SSN {p:SSN} — which W-4 box does it go in?",
        "Beneficiary social security number: {p:SSN}\nrelationship: spouse\ncheck the form for typos",
    ],
}

def family_kind(fid: str) -> str:
    return "A" if fid.split(".")[0] in ("neg", "mix") else "B"


def split_families(families=FAMILIES, salt: str = GENERATOR_VERSION) -> dict[str, str]:
    """Hold out one whole family per (kind, value group) when the group has >= 2 families."""
    groups: dict[tuple, list[str]] = {}
    for fid in families:
        kind, group, _ = fid.split(".")
        groups.setdefault((family_kind(fid), group), []).append(fid)
    assignment = {}
    for key, fids in sorted(groups.items()):
        fids = sorted(fids)
        held = None
        if len(fids) >= 2:
            held = fids[int(hashlib.sha256((salt + str(key)).encode()).hexdigest(), 16) % len(fids)]
        for fid in fids:
            assignment[fid] = "heldout" if fid == held else "train"
    return assignment


SLOT_RE = re.compile(r"\{([npx]):(\w+)\}")


def render(template: str, ctx: Ctx) -> tuple[str, list[Span], list[Span]]:
    text, spans, negatives, cursor = [], [], [], 0
    length = 0
    for m in SLOT_RE.finditer(template):
        literal = template[cursor:m.start()].replace("{{", "{").replace("}}", "}")
        text.append(literal)
        length += len(literal)
        kind, typ = m.groups()
        value = GEN[typ](ctx)
        start, end = length, length + len(value)
        if kind == "p":
            spans.append(Span(start, end, TARGET_OF[typ]))
        elif kind == "n":
            negatives.append(Span(start, end, typ))
        text.append(value)
        length = end
        cursor = m.end()
    tail = template[cursor:].replace("{{", "{").replace("}}", "}")
    text.append(tail)
    return "".join(text), spans, negatives


OPENERS = ["", "", "", "hi, ", "Hi team, ", "quick question: ", "Hey — ", "Could you help? "]
CONVERSATIONAL_FRAMES = {"chat", "policy"}


def generate(n_per_family: int, seed: int, names: tuple[list, list], families=FAMILIES) -> dict[str, list[Document]]:
    """Returns {"A_train", "A_heldout", "B_train", "B_heldout"} -> documents."""
    split = split_families(families)
    out = {f"{k}_{s}": [] for k in "AB" for s in ("train", "heldout")}
    for fid in sorted(families):
        rng = random.Random(int(hashlib.sha256(f"{seed}|{fid}".encode()).hexdigest()[:16], 16))
        bucket = f"{family_kind(fid)}_{split[fid]}"
        for i in range(n_per_family):
            template = rng.choice(families[fid])
            ctx = Ctx(rng=rng, names=names)
            opener = rng.choice(OPENERS) if fid.split(".")[2] in CONVERSATIONAL_FRAMES else ""
            body, spans, negatives = render(template, ctx)
            text = opener + body
            shift = len(opener)
            spans = [Span(s.start + shift, s.end + shift, s.label) for s in spans]
            negatives = [Span(s.start + shift, s.end + shift, s.label) for s in negatives]
            doc = Document(f"{fid}#{i:04d}", text, sorted(spans), [], sorted(negatives),
                           {"source": "synth", "generator": GENERATOR_VERSION, "family": fid, "split": split[fid],
                            "template_index": families[fid].index(template)})
            out[bucket].append(doc)
    return out


def validate_synthetic(doc: Document, names: tuple[list, list]) -> list[str]:
    """Annotation-policy checks for one generated document; returns a list of problems."""
    problems = []
    try:
        doc.validate()
    except ValueError as exc:
        problems.append(str(exc))
    for s in doc.spans:
        if s.label not in TARGET_SET:
            problems.append(f"label {s.label} outside scope")
        if s.label == "CREDITCARDCVV":
            cards = [(c.start, c.end) for c in doc.spans if c.label == "CREDITCARDNUMBER"]
            if not cvv_has_evidence(doc.text, s.start, s.end, cards):
                problems.append("CVV without evidence")
    # A pool name outside every target span would be an unannotated person name. Names inside
    # e-mail addresses / usernames are covered by those spans.
    pool = {n.lower() for n in names[0]} | {n.lower() for n in names[1]}
    for m in re.finditer(r"[A-Za-z][A-Za-z'-]+", doc.text):
        inside_target = any(s.start <= m.start() and m.end() <= s.end for s in doc.spans)
        if m.group().lower() in pool and not inside_target:
            problems.append(f"unannotated person name {m.group()!r}")
    return problems
