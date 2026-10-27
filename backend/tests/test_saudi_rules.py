"""The Saudi rules (backend/app/saudi_rules.py), alone and through POST /api/check.

No model is involved here. These rules keep working for Arabic text and Arabic-Indic digits
whatever the English-trained model predicts.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.saudi_rules import SaudiRuleDetector, detect_entities
from backend.tests.conftest import assert_error


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings, detector=SaudiRuleDetector()))


def check(client, text):
    response = client.post("/api/check", json={"text": text})
    assert response.status_code == 200
    return response.json()


# ---------- the original baseline tests (tests/test_regex_baseline.py in commit 142f268) ----------

def test_email_detection():
    result = detect_entities("Email: test@example.com")
    assert len(result) == 1
    assert result[0]["label"] == "private_email"
    assert (result[0]["start"], result[0]["end"]) == (7, 23)


def test_arabic_phone():
    text = "رقم الهاتف: 0551234567"
    result = detect_entities(text)
    assert len(result) == 1
    assert result[0]["label"] == "private_phone"
    assert (result[0]["start"], result[0]["end"]) == (12, 22)
    assert text[12:22] == "0551234567"


def test_multiple_entities():
    labels = {entity["label"] for entity in detect_entities("راسلوني على 0505283502 او test@example.com")}
    assert labels == {"private_email", "private_phone"}


def test_safe_message():
    assert detect_entities("السلام عليكم كيف الحال؟") == []


def test_sensitive_message():
    assert detect_entities("بريدي test@example.com") != []


def test_matched_values_are_not_returned():
    assert set(detect_entities("بريدي test@example.com")[0]) == {"label", "start", "end"}


# ---------- through the API ----------

@pytest.mark.parametrize(
    "text",
    ["السلام عليكم كيف الحال؟", "Draft a polite reply to a customer asking about a delayed refund."],
    ids=["arabic", "english"],
)
def test_clean_text_is_a_valid_result(client, text):
    body = check(client, text)
    assert body["decision"] == "ALLOW"
    assert body["reason"] == "No sensitive data found"
    assert body["safe_text"] == text
    assert body["detected"] == [] and body["spans"] == []


def test_arabic_phone_is_masked(client):
    body = check(client, "رقم الهاتف: 0551234567")
    assert body["decision"] == "BLOCK"
    assert body["reason"] == "Sensitive data found, masked copy returned"
    assert body["safe_text"] == "رقم الهاتف: [PHONE]"
    assert body["detected"] == [{"type": "PHONE", "label": "Phone number", "count": 1}]
    assert body["spans"] == [{"start": 12, "end": 22, "type": "PHONE"}]


@pytest.mark.parametrize("digits", ["٠٥٥١٢٣٤٥٦٧", "۰۵۵۱۲۳۴۵۶۷"], ids=["arabic-indic", "persian"])
def test_arabic_indic_and_persian_digits_are_masked(client, digits):
    body = check(client, f"رقم الهاتف: {digits}")
    assert body["safe_text"] == "رقم الهاتف: [PHONE]"
    assert digits not in body["safe_text"]


def test_national_id_and_iqama_are_masked(client):
    body = check(client, "رقم الهوية 1098765432 ورقم الإقامة 2123456789")
    assert body["decision"] == "BLOCK"
    assert body["safe_text"] == "رقم الهوية [NATIONAL_ID] ورقم الإقامة [IQAMA]"
    assert body["detected"] == [
        {"type": "NATIONAL_ID", "label": "National ID", "count": 1},
        {"type": "IQAMA", "label": "Iqama number", "count": 1},
    ]


def test_phone_and_email_in_one_text(client):
    body = check(client, "راسلوني على 0505283502 او test@example.com")
    assert body["safe_text"] == "راسلوني على [PHONE] او [EMAIL]"
    assert [d["type"] for d in body["detected"]] == ["PHONE", "EMAIL"]


def test_international_phone_format(client):
    assert check(client, "Call 00966551234567 today")["safe_text"] == "Call [PHONE] today"


def test_spans_point_at_the_masked_values(client):
    text = "اتصل على 0551234567 او ali@example.com شكرا"
    body = check(client, text)
    assert [text[s["start"]:s["end"]] for s in body["spans"]] == ["0551234567", "ali@example.com"]


def test_detected_values_never_reach_the_audit_log(client, settings):
    check(client, "رقم الهوية 1098765432 والبريد test@example.com")
    raw = b"".join(p.read_bytes() for p in settings.db_path.parent.glob("washq.sqlite3*"))
    assert b"1098765432" not in raw and b"test@example.com" not in raw
    assert client.get("/api/logs").json()["items"][0]["masking"] == "2 items masked"


def test_validation_still_applies(client):
    assert_error(client.post("/api/check", json={"text": "   "}), 422)


# Known gaps of the Saudi rules on their own. They are expected to fail; strict=True makes the
# test suite report it when a change fixes one, so the marker can be removed.

@pytest.mark.xfail(strict=True, reason="Email followed by a full stop is not detected")
def test_known_gap_email_at_end_of_sentence(client):
    assert check(client, "email: ali@company.sa.")["safe_text"] == "email: [EMAIL]."


@pytest.mark.xfail(strict=True, reason="+966 numbers written with spaces are not detected")
def test_known_gap_spaced_international_phone(client):
    assert "[PHONE]" in check(client, "Call +966 5 5123 4567")["safe_text"]


@pytest.mark.xfail(strict=True, reason="IDs written directly after an Arabic word are not detected")
def test_known_gap_id_attached_to_arabic_word(client):
    assert check(client, "هويتي1098765432")["safe_text"] == "هويتي[NATIONAL_ID]"
