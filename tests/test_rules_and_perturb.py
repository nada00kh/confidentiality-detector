import re
from pathlib import Path

import pytest

from confidentiality_detector.challenge import load_challenge, parse_case
from confidentiality_detector.detectors.hybrid import merge
from confidentiality_detector.detectors.rules import RuleDetector, iban_valid, luhn_valid
from confidentiality_detector.documents import Document, Span
from confidentiality_detector.perturb import FormatPerturber

ROOT = Path(__file__).resolve().parents[1]
rules = RuleDetector()


def found(text):
    return {(text[s.start:s.end], s.label) for s in rules.detect(text)}


def test_validators():
    assert luhn_valid("4111111111111111") and not luhn_valid("4111111111111112")
    assert iban_valid("DE89 3704 0044 0532 0130 00") and not iban_valid("DE88 3704 0044 0532 0130 00")


@pytest.mark.parametrize("text,expected", [
    ("mail me at jane.doe+x@mail.example.org.", ("jane.doe+x@mail.example.org", "EMAIL")),
    ("card 4111 1111 1111 1111 exp 09/27", ("4111 1111 1111 1111", "CREDITCARDNUMBER")),
    ("IBAN DE89 3704 0044 0532 0130 00 THANKS", ("DE89 3704 0044 0532 0130 00", "IBAN")),
    ("server 10.0.4.12:5432 is down", ("10.0.4.12", "IPV4")),
    ("my ssn is 521-47-8830", ("521-47-8830", "SSN")),
    ("CVV: 737", ("737", "CREDITCARDCVV")),
    ("account no. 5560 2214 9083 was credited", ("5560 2214 9083", "ACCOUNTNUMBER")),
    ("DB_PASSWORD=Q7uX-33kd-PLm", ("Q7uX-33kd-PLm", "PASSWORD")),
    ("my password is Hunter2.", ("Hunter2", "PASSWORD")),
    ("postgres://app:s3cr3t@10.0.0.8:5432/db", ("s3cr3t", "PASSWORD")),
    ("ssh ubuntu@34.201.18.77", ("ubuntu", "USERNAME")),
    ("username: k.villanueva", ("k.villanueva", "USERNAME")),
    ("call (415) 555-0147 today", ("(415) 555-0147", "PHONENUMBER")),
])
def test_rule_positives(text, expected):
    assert expected in found(text)


@pytest.mark.parametrize("text", [
    "Upgrade from version 1.2.3.4 to 1.2.4",
    "I forgot my password and the reset email never arrives",
    "Order 112-4471983-5520193 is late",
    "The account number field should accept 8 to 12 digits",
    "pass along the notes from the password protected doc",
    "Compute 4111 * 1111 + 1111",
])
def test_rule_negatives(text):
    assert found(text) == set()


def test_hybrid_merge_prefers_rule_boundaries_for_structured_types():
    model = [Span(0, 8, "EMAIL"), Span(20, 25, "FIRSTNAME")]
    rule = [Span(0, 12, "EMAIL"), Span(20, 25, "USERNAME"), Span(40, 44, "CREDITCARDCVV")]
    merged = merge(model, rule)
    assert [s.key() for s in merged] == [(0, 12, "EMAIL"), (20, 25, "FIRSTNAME"), (40, 44, "CREDITCARDCVV")]


def test_format_perturbation_keeps_offsets_and_validity():
    text = "Hi Ann, card 1234567812345678 and IBAN XX00 and pin 1111. Bye Ann Lee"
    d = Document("p1", text, [Span(3, 6, "FIRSTNAME"), Span(13, 29, "CREDITCARDNUMBER"), Span(39, 43, "IBAN"),
                              Span(62, 65, "FIRSTNAME"), Span(66, 69, "LASTNAME")],
                 negative_spans=[Span(52, 56, "PIN")])
    for family in ("A", "B"):
        out = FormatPerturber(family)(d)
        assert out.text[out.negative_spans[0].start:out.negative_spans[0].end] == "1111"
        card = out.text[out.spans[1].start:out.spans[1].end]
        assert luhn_valid(re.sub(r"\D", "", card))
        assert iban_valid(out.text[out.spans[2].start:out.spans[2].end])
        assert out.text[out.spans[0].start:out.spans[0].end].lower() == out.text[out.spans[3].start:out.spans[3].end].lower()


def test_challenge_markup():
    d = parse_case("c", ["t"], "hi [[FIRSTNAME:Ann]] at [[~AMBIG:127.0.0.1]] v[[!VERSION:1.2.3.4]]")
    assert d.text == "hi Ann at 127.0.0.1 v1.2.3.4"
    assert [d.text[s.start:s.end] for s in d.spans] == ["Ann"]
    assert d.ignore_spans[0].label == "AMBIG" and d.negative_spans[0].label == "VERSION"


def test_challenge_file_is_frozen():
    path = ROOT / "data/challenge/challenge_v1.txt"
    expected = (ROOT / "data/challenge/challenge_v1.sha256").read_text().split()[0]
    import hashlib
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    assert len(load_challenge(path)) == 154


# --- rules v3 (validation/dev-driven changes) -------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ('{"card_number": "5555 5555 5555 4444", "exp": "08/28", "security_code": "925"}', ("925", "CREDITCARDCVV")),
    ("cvv2: 552", ("552", "CREDITCARDCVV")),
    ("the code on the back of the card is 4096", ("4096", "CREDITCARDCVV")),
    ('{"login": "kokafor", "password": "Bluefin#7731"}', ("Bluefin#7731", "PASSWORD")),
    ('{"login": "kokafor", "password": "Bluefin#7731"}', ("kokafor", "USERNAME")),
    ("CREATE USER report_reader WITH PASSWORD 'Rr-2291-xq!';", ("Rr-2291-xq!", "PASSWORD")),
    ("ALTER USER 'svc_ingest'@'%' IDENTIFIED BY 'Ing3st!Now';", ("Ing3st!Now", "PASSWORD")),
    ("psql -h db.internal -U reporting_ro", ("reporting_ro", "USERNAME")),
    ("logged in as mbrandt but the dashboard is stale", ("mbrandt", "USERNAME")),
    ("files under /home/rfarhan/reports", ("rfarhan", "USERNAME")),
    ("machine api.internal login deploy-ci password Dc1!q8Zr", ("Dc1!q8Zr", "PASSWORD")),
    ("the passcode is THZVUHly2D0x", ("THZVUHly2D0x", "PASSWORD")),
    ("Presto/2.9.178 Version/12.00) at IP 168.95.9.25.", ("168.95.9.25", "IPV4")),
])
def test_rule_v3_positives(text, expected):
    assert expected in found(text)


@pytest.mark.parametrize("text", [
    "0004 is your security code for the next online consultation",  # weak cue, no card context
    "enter the passcode 4708 at the entrance",                        # numeric passcode = PIN
    "the firmware went from 2.4.1.7 to 2.4.2.0 and now it fails",     # versions, not hosts
    "pip reports version 1.4.0.2",
    "git push -u origin main",
    "Our office is in room 482 on the 4th floor",
    "files under /home/shared/reports",
])
def test_rule_v3_negatives(text):
    assert found(text) == set()


def test_cvv_evidence_policy():
    from confidentiality_detector.labels import cvv_has_evidence

    def ev(text, value):
        i = text.index(value)
        return cvv_has_evidence(text, i, i + len(value))

    assert ev("CVV: 482", "482")
    assert ev("the 3 digits on the back are 204, the security code box", "204")
    assert ev("card 4111111111111111 exp 09/27 and 737", "737")          # card context
    assert ev("card security code 318", "318")                           # weak cue + card word
    assert not ev("0004 is your security code for the consultation", "0004")
    assert not ev("never share your 482 or 1234 online", "482")          # concept-slot noise


def test_policy_v3_ignores_cvv_without_evidence():
    from confidentiality_detector.documents import document_from_ai4privacy
    from confidentiality_detector.labels import V2, V3

    record = {"id": 9, "source_text": "Never share your 482 with anyone. Card 4111111111111111, CVV 737.",
              "privacy_mask": [{"value": "482", "start": 17, "end": 20, "label": "CREDITCARDCVV"},
                               {"value": "4111111111111111", "start": 39, "end": 55, "label": "CREDITCARDNUMBER"},
                               {"value": "737", "start": 61, "end": 64, "label": "CREDITCARDCVV"}]}
    v2, v3 = document_from_ai4privacy(record, V2), document_from_ai4privacy(record, V3)
    assert [s.label for s in v2.spans].count("CREDITCARDCVV") == 2
    # "482" is within the card-context window of the card number here, so it keeps evidence:
    assert [s.label for s in v3.spans].count("CREDITCARDCVV") == 2
    far = {"id": 10, "source_text": "Never share your 482 with anyone online, it is the rule here.",
           "privacy_mask": [{"value": "482", "start": 17, "end": 20, "label": "CREDITCARDCVV"}]}
    d = document_from_ai4privacy(far, V3)
    assert not d.spans and [s.label for s in d.ignore_spans] == ["CVV_NO_EVIDENCE"] and d.gold_decision() == "AMBIGUOUS"


@pytest.mark.parametrize("text", [
    "rolled back 7.5.0.10 on the canary and health checks passed",   # version, small first octet, no network context
    "please mention tracking 2899564846 in the reply",                # identifier cue before a phone-shaped number
    "The confirmation for 679-2737025-3585125 bounced",              # 3-7-7 grouping is not a card layout
    "the sku 4006381333931 does not scan",                           # identifier cue before a 13-digit barcode
    "bridge 182 6291 3294 says the host has not joined",             # meeting id
    "USPS 9400 1118 9922 3456 7811 04 is late",                      # card-shaped prefix of a longer number
])
def test_rule_v3_identifier_negatives(text):
    assert found(text) == set()


@pytest.mark.parametrize("text,expected", [
    ("ssh deploy@10.0.0.5 failed", ("10.0.0.5", "IPV4")),
    ("bind=8.8.4.4 in resolv.conf", ("8.8.4.4", "IPV4")),
    ("host 3.14.15.92 is unreachable", ("3.14.15.92", "IPV4")),
    ("pay with 4111 1111 1111 1111 today", ("4111 1111 1111 1111", "CREDITCARDNUMBER")),
])
def test_rule_v3_network_and_card_context_positives(text, expected):
    assert expected in found(text)
