"""The Saudi rules are a demo-only extension, supplemental to the evaluated core detector.

Core system (evaluated, including Challenge v2): the frozen R3 model + rules v3, strict mode.
Demo-only extension (never evaluated): the Saudi rules in backend/app/saudi_rules.py.

The rules checked here (labels.LABEL_PRIORITY, labels.SAUDI_PATTERN_HINTS):
  * the Saudi rules may add masked values, but where they overlap a core finding, the core
    finding's type is kept and the value is masked once;
  * when a Saudi rule matches a whole value that the core detector typed differently, the response
    adds a secondary hint in `pattern_hints`; hints change nothing else (decision, types, counts,
    spans, masked text) and are never stored or counted;
  * the decision, detected types, spans, masked text, audit log and statistics agree.

All texts are fictional. Mocked core results copy what the frozen checkpoint returned for the
same texts (CPU, 2026-10-30); the real-model tests check those texts with the checkpoint and
are skipped when it is not available.
"""

import json

import pytest
from confidentiality_detector.policy import Decision, Finding
from fastapi.testclient import TestClient

from backend.app.detection import CombinedDetector, Entity
from backend.app.labels import MODEL_LABEL_TO_CODE, SAUDI_LABEL_TO_CODE
from backend.app.main import create_app
from backend.app.model_detector import ModelDetector
from backend.app.sanitizer import Span, pattern_hint_summary, sanitize
from backend.app.saudi_rules import SaudiRuleDetector, detect_entities

# The README's German IBAN example, spaced: "0532 0130 00" inside it has the shape of a Saudi mobile number.
IBAN_TEXT = "Please wire the deposit to DE89 3704 0044 0532 0130 00."
MIXED = ("Log in as k.alharbi with password Qm7!pX2v, then call 0559876543 and send the iqama copy (2123456789) "
         "to hr@example.com.")

NATIONAL_ID_NOTE = "Also matches a Saudi national ID pattern (demo rule)."
IQAMA_NOTE = "Also matches an Iqama-like pattern (demo rule)."
MOBILE_NOTE = "Also matches a Saudi mobile number pattern (demo rule)."


def check(client, text):
    response = client.post("/api/check", json={"text": text})
    assert response.status_code == 200
    return response.json()


def hint(code, label, pattern, note, count=1):
    return {"type": code, "label": label, "pattern": pattern, "note": note, "count": count}


# ---------- the merge rule, with the Saudi rules' real positions ----------

def test_saudi_phone_rule_matches_inside_a_spaced_german_iban():
    # The cause of the former mislabelling: on its own, the Saudi rule sees a phone number here.
    assert detect_entities(IBAN_TEXT) == [{"label": "private_phone", "start": 42, "end": 54}]


def test_iban_keeps_its_type_and_gets_no_hint_when_the_saudi_phone_rule_matches_inside_it():
    # The Saudi match covers only part of the IBAN, so it says nothing about the IBAN's format.
    saudi = SaudiRuleDetector().detect(IBAN_TEXT)
    for entities in ([Entity(27, 54, "IBAN"), *saudi], [*saudi, Entity(27, 54, "IBAN")]):
        result = sanitize(IBAN_TEXT, entities)
        assert result.safe_text == "Please wire the deposit to [IBAN]."
        assert result.spans == [Span(27, 54, "IBAN", ())]
        assert result.counts == {"IBAN": 1}
        assert pattern_hint_summary(result.spans) == []


@pytest.mark.parametrize("value, code", [
    ("0551234567", "PHONE"), ("+966551234567", "PHONE"), ("00966551234567", "PHONE"), ("055 123 4567", "PHONE"),
    ("٠٥٥١٢٣٤٥٦٧", "PHONE"), ("1098765432", "NATIONAL_ID"), ("2123456789", "IQAMA"), ("٢١٢٣٤٥٦٧٨٩", "IQAMA"),
])
def test_saudi_value_missed_by_the_core_detector_gets_the_saudi_type_and_no_hint(value, code):
    text = f"Number {value} please."
    result = sanitize(text, SaudiRuleDetector().detect(text))
    assert result.safe_text == f"Number [{code}] please."
    assert pattern_hint_summary(result.spans) == []


# What the frozen detector returned for each value (see the real-model tests below), with the Saudi rule
# matching the same characters: one masked value, with the core type and, where the types differ, a hint.
OVERLAPS = [
    ("0551234567", "ACCOUNTNUMBER", "ACCOUNT_NUMBER", ("SAUDI_MOBILE",)),
    ("00966551234567", "CREDITCARDNUMBER", "CARD_NUMBER", ("SAUDI_MOBILE",)),
    ("055 123 4567", "PHONENUMBER", "PHONE", ()),
    ("1098765432", "ACCOUNTNUMBER", "ACCOUNT_NUMBER", ("SAUDI_NATIONAL_ID",)),
    ("2123456789", "ACCOUNTNUMBER", "ACCOUNT_NUMBER", ("SAUDI_IQAMA",)),
    ("٢١٢٣٤٥٦٧٨٩", "PHONENUMBER", "PHONE", ("SAUDI_IQAMA",)),
    ("hr@example.com", "EMAIL", "EMAIL", ()),
]


@pytest.mark.parametrize("value, core_label, code, hints", OVERLAPS)
def test_value_found_by_both_is_masked_once_with_the_core_type(value, core_label, code, hints):
    text = f"Number {value} please."
    start = text.index(value)
    core = [Entity(start, start + len(value), core_label)]
    saudi = SaudiRuleDetector().detect(text)
    assert [(e.start, e.end) for e in saudi] == [(start, start + len(value))]

    result = sanitize(text, core + saudi)
    assert result.safe_text == f"Number [{code}] please."
    assert result.counts == {code: 1}
    assert result.spans == [Span(start, start + len(value), code, hints)]
    # The hint changes nothing else: the same masked text, spans and counts as the core finding alone.
    core_only = sanitize(text, core)
    assert (core_only.safe_text, core_only.counts) == (result.safe_text, result.counts)
    assert [(s.start, s.end, s.type) for s in core_only.spans] == [(s.start, s.end, s.type) for s in result.spans]


def test_ordinary_account_number_gets_no_hint():
    text = "My account number is 40018822 at the credit union."
    assert SaudiRuleDetector().detect(text) == []
    result = sanitize(text, [Entity(21, 29, "ACCOUNTNUMBER")])
    assert result.safe_text == "My account number is [ACCOUNT_NUMBER] at the credit union."
    assert pattern_hint_summary(result.spans) == []


def test_hint_summary_counts_per_type_and_pattern_without_values():
    text = "IDs 1098765432 and 1045678901, iqama 2123456789, mobile 0551234567."
    values = ["1098765432", "1045678901", "2123456789", "0551234567"]
    core = [Entity(text.index(v), text.index(v) + len(v), "ACCOUNTNUMBER") for v in values]
    summary = pattern_hint_summary(sanitize(text, core + SaudiRuleDetector().detect(text)).spans)
    assert summary == [
        hint("ACCOUNT_NUMBER", "Account number", "SAUDI_NATIONAL_ID", NATIONAL_ID_NOTE, 2),
        hint("ACCOUNT_NUMBER", "Account number", "SAUDI_IQAMA", IQAMA_NOTE),
        hint("ACCOUNT_NUMBER", "Account number", "SAUDI_MOBILE", MOBILE_NOTE),
    ]
    assert not any(v in json.dumps(summary) for v in values)


# ---------- through the API: everything the user and the admin see agrees ----------

class CoreResult:
    """Stands in for the frozen detector with a fixed strict result."""

    def __init__(self, *findings):
        labels = tuple(sorted({f.label for f in findings}))
        self.result = (Decision("BLOCK", "SENSITIVE_ENTITIES", "strict", labels, findings) if findings
                       else Decision("ALLOW", "NO_SENSITIVE_ENTITIES", "strict", ()))

    def inspect(self, text, mode=None):
        return self.result


# The core findings of MIXED as the checkpoint returned them.
MIXED_CORE = (Finding(10, 19, "USERNAME", "model+rules"), Finding(34, 42, "PASSWORD", "model+rules"),
              Finding(54, 64, "ACCOUNTNUMBER", "model"), Finding(90, 100, "ACCOUNTNUMBER", "model"),
              Finding(105, 119, "EMAIL", "rules"))


def test_decision_types_spans_masked_text_log_and_stats_agree(make_client, settings):
    # The Arabic-Indic number at the end is one that the checkpoint misses, so only the Saudi rule finds it.
    text = MIXED + " Backup: ٠٥٥١٢٣٤٥٦٧"
    client = make_client(detector=CombinedDetector(ModelDetector(CoreResult(*MIXED_CORE)), SaudiRuleDetector()))
    body = check(client, text)

    assert body["decision"] == "BLOCK"
    assert body["safe_text"] == ("Log in as [USERNAME] with password [PASSWORD], then call [ACCOUNT_NUMBER] and send the "
                                 "iqama copy ([ACCOUNT_NUMBER]) to [EMAIL]. Backup: [PHONE]")
    span_types = [s["type"] for s in body["spans"]]
    assert span_types == ["USERNAME", "PASSWORD", "ACCOUNT_NUMBER", "ACCOUNT_NUMBER", "EMAIL", "PHONE"]
    counts = {d["type"]: d["count"] for d in body["detected"]}
    assert counts == {code: span_types.count(code) for code in span_types}
    assert body["safe_text"].count("[") == len(body["spans"])
    assert body["pattern_hints"] == [hint("ACCOUNT_NUMBER", "Account number", "SAUDI_MOBILE", MOBILE_NOTE),
                                     hint("ACCOUNT_NUMBER", "Account number", "SAUDI_IQAMA", IQAMA_NOTE)]

    # Audit log and statistics: primary types only; hints are neither stored nor counted.
    logs = client.get("/api/logs").json()
    item = logs["items"][0]
    assert {d["type"]: d["count"] for d in item["detected"]} == counts
    assert (item["decision"], item["masking"]) == ("BLOCK", "6 items masked")
    stats = client.get("/api/stats").json()
    assert (stats["total"], stats["blocked"], stats["allowed"]) == (1, 1, 0)
    assert {d["type"]: d["count"] for d in stats["top_types"]} == counts
    raw = b"".join(p.read_bytes() for p in settings.db_path.parent.glob("washq.sqlite3*"))
    for blob in (json.dumps(logs), json.dumps(stats), raw.decode("latin-1")):
        assert "SAUDI_" not in blob and "demo rule" not in blob


def test_hints_change_nothing_but_the_hint_field(make_client):
    core = ModelDetector(CoreResult(*MIXED_CORE))
    full = check(make_client(detector=CombinedDetector(core, SaudiRuleDetector())), MIXED)
    core_only = check(make_client(detector=CombinedDetector(core)), MIXED)
    assert core_only["pattern_hints"] == [] and len(full["pattern_hints"]) == 2
    for key in ("decision", "reason", "detected", "safe_text", "spans"):
        assert full[key] == core_only[key]


def test_allow_has_no_hints(make_client):
    client = make_client(detector=CombinedDetector(ModelDetector(CoreResult()), SaudiRuleDetector()))
    body = check(client, "Please summarise the attached meeting notes for the team.")
    assert (body["decision"], body["pattern_hints"]) == ("ALLOW", [])


# ---------- with the real checkpoint ----------

FIXTURES = [
    IBAN_TEXT,
    "My account number is 40018822 at the credit union.",
    "Please call Khalid on 0551234567 tomorrow morning.",
    "Please call Khalid on 00966551234567 tomorrow morning.",
    "Please call Khalid on 055 123 4567 tomorrow morning.",
    "The visitor's national ID is 1098765432.",
    "Iqama number 2123456789 expires next month.",
    MIXED,
    "رقم الهاتف: ٠٥٥١٢٣٤٥٦٧",
    "رقم الإقامة ٢١٢٣٤٥٦٧٨٩ ينتهي الشهر القادم",
    "Ticket 1000234567 was escalated to tier 2.",
    "Please summarise the attached meeting notes for the team.",
]


@pytest.fixture
def core_client(settings, real_model):
    """The API with the evaluated core detector only."""
    return TestClient(create_app(settings, detector=CombinedDetector(real_model)))


@pytest.fixture
def full_client(settings, real_model):
    """The API as it runs: the core detector plus the Saudi extension (main.build_detector)."""
    return TestClient(create_app(settings, detector=CombinedDetector(real_model, SaudiRuleDetector())))


def core_entities(real_model, text):
    decision = real_model._inspector.inspect(text, "strict")
    return decision, [Entity(f.start, f.end, f.label) for f in decision.findings]


def api_spans(body):
    return [(s["start"], s["end"], s["type"]) for s in body["spans"]]


@pytest.mark.real_model
@pytest.mark.parametrize("text", FIXTURES)
def test_core_results_match_direct_strict_inference(core_client, real_model, text):
    # Before the Saudi findings are added, the API gives the frozen detector's own answer.
    decision, entities = core_entities(real_model, text)
    body = check(core_client, text)
    assert body["decision"] == decision.decision
    # The direct findings, with type codes and whole-word masking applied (sanitizer.expand_to_word).
    assert api_spans(body) == [(s.start, s.end, s.type) for s in sanitize(text, entities).spans]
    if text.isascii():
        assert api_spans(body) == [(e.start, e.end, MODEL_LABEL_TO_CODE[e.label]) for e in entities]
    assert body["pattern_hints"] == []


@pytest.mark.real_model
@pytest.mark.parametrize("text", FIXTURES)
def test_saudi_findings_are_only_added_to_the_core_results(full_client, real_model, text):
    decision, core = core_entities(real_model, text)
    saudi = SaudiRuleDetector().detect(text)
    body = check(full_client, text)
    spans = api_spans(body)

    # The decision changes only from ALLOW to BLOCK, and only when a Saudi rule found something.
    assert body["decision"] == ("BLOCK" if decision.decision == "BLOCK" or saudi else "ALLOW")
    # Every core finding is masked with its own type ...
    for e in core:
        assert any(s <= e.start and e.end <= t and code == MODEL_LABEL_TO_CODE[e.label] for s, t, code in spans)
    # ... and a span without a core finding comes from a Saudi rule and has the Saudi type.
    for s, t, code in spans:
        if not any(s <= e.start and e.end <= t for e in core):
            assert any(s <= e.start and e.end <= t and code == SAUDI_LABEL_TO_CODE[e.label] for e in saudi)
    # The text returned contains exactly one placeholder per span (none for ALLOW).
    assert body["safe_text"].count("[") == len(spans)
    # Hints only explain values the core detector typed.
    core_types = {MODEL_LABEL_TO_CODE[e.label] for e in core}
    assert {h["type"] for h in body["pattern_hints"]} <= core_types


@pytest.mark.real_model
def test_german_iban_is_masked_as_iban_without_a_hint(full_client):
    body = check(full_client, IBAN_TEXT)
    assert body["safe_text"] == "Please wire the deposit to [IBAN]."
    assert body["detected"] == [{"type": "IBAN", "label": "IBAN", "count": 1}]
    assert api_spans(body) == [(27, 54, "IBAN")]
    assert body["pattern_hints"] == []


@pytest.mark.real_model
@pytest.mark.parametrize("text, types, patterns", [
    ("My account number is 40018822 at the credit union.", {"ACCOUNT_NUMBER"}, []),
    ("Please call Khalid on 0551234567 tomorrow morning.", {"PERSON_NAME", "ACCOUNT_NUMBER"},
     [("ACCOUNT_NUMBER", "SAUDI_MOBILE")]),
    ("Please call Khalid on 00966551234567 tomorrow morning.", {"PERSON_NAME", "CARD_NUMBER"},
     [("CARD_NUMBER", "SAUDI_MOBILE")]),
    ("Please call Khalid on 055 123 4567 tomorrow morning.", {"PERSON_NAME", "PHONE"}, []),
    ("The visitor's national ID is 1098765432.", {"ACCOUNT_NUMBER"}, [("ACCOUNT_NUMBER", "SAUDI_NATIONAL_ID")]),
    ("Iqama number 2123456789 expires next month.", {"ACCOUNT_NUMBER"}, [("ACCOUNT_NUMBER", "SAUDI_IQAMA")]),
    ("رقم الهاتف: ٠٥٥١٢٣٤٥٦٧", {"PHONE"}, []),  # missed by the core detector: the Saudi rule's own type
    ("رقم الإقامة ٢١٢٣٤٥٦٧٨٩ ينتهي الشهر القادم", {"PHONE"}, [("PHONE", "SAUDI_IQAMA")]),  # rules v3: a phone number
])
def test_types_and_hints_shown_for_saudi_values(full_client, text, types, patterns):
    # What the demo shows: the core detector's type wherever it found the value, plus a demo-rule hint.
    body = check(full_client, text)
    assert body["decision"] == "BLOCK"
    assert {d["type"] for d in body["detected"]} == types
    assert [(h["type"], h["pattern"]) for h in body["pattern_hints"]] == patterns
