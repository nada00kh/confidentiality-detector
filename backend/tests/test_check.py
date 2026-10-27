import logging

import pytest

from backend.app.detection import Entity
from backend.app.errors import DETECTION_FAILED, DETECTION_UNAVAILABLE, STORAGE_FAILED
from backend.app.main import MAX_TEXT_LENGTH
from backend.app.storage import REASON_CLEAN, REASON_MASKED, REASON_NOT_MASKED, StorageError
from backend.tests.conftest import SECRET, FakeDetector, assert_error


# ---------- unchanged endpoints ----------

def test_health_still_works(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_educational_scan_endpoint_is_gone(client):
    assert_error(client.post("/scan", json={"text": "hello"}), 404)


def test_check_only_accepts_post(client):
    assert_error(client.get("/api/check"), 405)


# ---------- no detector connected: valid input gets 503, never a decision ----------

@pytest.mark.parametrize(
    "text",
    [
        "Draft a polite reply to a customer asking about a delayed refund.",
        "لخص شكوى العميل حول الفاتورة",
        "  text with surrounding spaces  ",
        "x",
        "x" * MAX_TEXT_LENGTH,
    ],
    ids=["english", "arabic", "surrounding-spaces", "one-char", "exactly-max-length"],
)
def test_valid_text_returns_503_without_a_decision(client, text):
    detail = assert_error(client.post("/api/check", json={"text": text}), 503)
    assert detail == DETECTION_UNAVAILABLE


def test_unavailable_detection_records_nothing(client):
    client.post("/api/check", json={"text": f"My card is {SECRET}"})
    assert client.get("/api/stats").json()["total"] == 0


def test_503_does_not_echo_the_text(client):
    response = client.post("/api/check", json={"text": f"My card is {SECRET}"})
    assert response.status_code == 503
    assert SECRET not in response.text


# ---------- invalid input ----------

def test_missing_text(client):
    detail = assert_error(client.post("/api/check", json={}), 422)
    assert detail == 'The "text" field is required.'


def test_missing_body(client):
    assert_error(client.post("/api/check"), 422)


@pytest.mark.parametrize("value", [123, 1.5, True, None, ["a"], {"a": "b"}])
def test_wrong_type(client, value):
    detail = assert_error(client.post("/api/check", json={"text": value}), 422)
    assert detail == 'The "text" field must be a string.'


def test_empty_text(client):
    detail = assert_error(client.post("/api/check", json={"text": ""}), 422)
    assert detail == 'The "text" field must not be empty.'


@pytest.mark.parametrize("text", [" ", "   ", "\n\t", "　"], ids=["space", "spaces", "newline-tab", "ideographic-space"])
def test_whitespace_only_text(client, text):
    detail = assert_error(client.post("/api/check", json={"text": text}), 422)
    assert detail == 'The "text" field must not be empty.'


def test_oversized_text(client):
    detail = assert_error(client.post("/api/check", json={"text": "x" * (MAX_TEXT_LENGTH + 1)}), 422)
    assert detail == 'The "text" field is too long (maximum 10,000 characters).'


def test_extra_fields_are_rejected(client):
    # A client must not be able to send its own decision or safe text.
    response = client.post("/api/check", json={"text": "hello", "decision": "ALLOW", "safe_text": "hello"})
    detail = assert_error(response, 422)
    assert detail == "The request contains fields that are not allowed."


@pytest.mark.parametrize("body", [["text"], "text", 42], ids=["list", "string", "number"])
def test_body_must_be_a_json_object(client, body):
    detail = assert_error(client.post("/api/check", json=body), 422)
    assert detail == "The request body must be a JSON object."


def test_invalid_json(client):
    response = client.post(
        "/api/check", content=b'{"text": "unterminated', headers={"content-type": "application/json"}
    )
    detail = assert_error(response, 422)
    assert detail == "The request body is not valid JSON."


@pytest.mark.parametrize(
    "kwargs",
    [
        {"json": {"text": [SECRET]}},
        {"json": {"text": {"card": SECRET}}},
        {"json": {"text": SECRET * 1000}},
        {"json": {"text": "hello", SECRET: SECRET}},
        {"json": {"note": SECRET}},
        {"json": [SECRET]},
        {"json": SECRET},
        {"content": f'{{"text": "{SECRET}'.encode(), "headers": {"content-type": "application/json"}},
    ],
    ids=["in-list", "in-object", "oversized", "extra-field-name-and-value", "only-unknown-field",
         "list-body", "string-body", "invalid-json"],
)
def test_error_responses_never_echo_input(client, kwargs):
    response = client.post("/api/check", **kwargs)
    assert_error(response, 422)
    assert "SECRET" not in response.text


# ---------- with a detector (test-only fake) ----------

SAMPLE = "Summarize the complaint from customer Ahmed Alotaibi, ID 1098765432, about invoice #4471."


def test_name_and_id_return_block_with_masked_copy(make_client):
    detector = FakeDetector(("Ahmed", "FIRSTNAME"), ("Alotaibi", "LASTNAME"), ("1098765432", "national_id"))
    response = make_client(detector=detector).post("/api/check", json={"text": SAMPLE})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"operation_id", "decision", "reason", "detected", "safe_text", "spans"}
    assert body["operation_id"] == "WSQ-000001"
    assert body["decision"] == "BLOCK"
    assert body["reason"] == "Sensitive data found, masked copy returned"
    assert body["safe_text"] == (
        "Summarize the complaint from customer [PERSON_NAME] [PERSON_NAME], ID [NATIONAL_ID], about invoice #4471."
    )
    assert body["detected"] == [
        {"type": "PERSON_NAME", "label": "Person name", "count": 2},
        {"type": "NATIONAL_ID", "label": "National ID", "count": 1},
    ]
    assert body["spans"] == [
        {"start": 38, "end": 43, "type": "PERSON_NAME"},
        {"start": 44, "end": 52, "type": "PERSON_NAME"},
        {"start": 57, "end": 67, "type": "NATIONAL_ID"},
    ]
    for value in ("Ahmed", "Alotaibi", "1098765432"):
        assert value not in body["safe_text"]


def test_passwords_and_cards_are_masked_and_blocked(make_client):
    text = f"The password is Riyadh@2024 and card {SECRET}."
    detector = FakeDetector(("Riyadh@2024", "PASSWORD"), (SECRET, "CREDITCARDNUMBER"))
    body = make_client(detector=detector).post("/api/check", json={"text": text}).json()
    assert body["decision"] == "BLOCK"
    assert body["safe_text"] == "The password is [PASSWORD] and card [CARD_NUMBER]."
    assert SECRET not in body["safe_text"] and "Riyadh@2024" not in body["safe_text"]


@pytest.mark.parametrize(
    "text",
    ["Draft a polite reply to a customer asking about a delayed refund.", "  spaces kept  \n", "اكتب رداً مهذباً"],
    ids=["english", "surrounding-whitespace", "arabic"],
)
def test_clean_text_returns_allow_with_the_same_text(make_client, text):
    body = make_client(detector=FakeDetector()).post("/api/check", json={"text": text}).json()
    assert body["decision"] == "ALLOW"
    assert body["reason"] == REASON_CLEAN
    assert body["safe_text"] == text
    assert body["detected"] == [] and body["spans"] == []


def test_one_detection_is_enough_for_block(make_client):
    body = make_client(detector=FakeDetector(("a@b.co", "EMAIL"))).post("/api/check", json={"text": "mail a@b.co"}).json()
    assert body["decision"] == "BLOCK"
    assert body["safe_text"] == "mail [EMAIL]"


def test_spans_use_javascript_string_positions(make_client):
    # The emoji is 1 character in Python but 2 in JavaScript, which is what the frontend uses.
    text = "😀 Call 0551234567"
    body = make_client(detector=FakeDetector(("0551234567", "PHONENUMBER"))).post("/api/check", json={"text": text}).json()
    assert body["spans"] == [{"start": 8, "end": 18, "type": "PHONE"}]
    assert body["safe_text"] == "😀 Call [PHONE]"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "not a list",
        [("start", "end")],
        [{"start": 0, "end": 4, "label": "EMAIL"}],
    ],
    ids=["none", "string", "tuple", "dict-instead-of-entity"],
)
def test_malformed_detector_output_fails_closed(make_client, raw):
    response = make_client(detector=FakeDetector(raw=raw)).post("/api/check", json={"text": "test text"})
    assert assert_error(response, 503) == DETECTION_FAILED


@pytest.mark.parametrize(
    "entities",
    [
        [Entity(-1, 3, "EMAIL")],
        [Entity(3, 3, "EMAIL")],
        [Entity(5, 2, "EMAIL")],
        [Entity(0, 999, "EMAIL")],
        [Entity(0, 4, "UNKNOWN_LABEL")],
        [Entity(0, 4, "EMAIL"), Entity(5, 9, "UNKNOWN_LABEL")],
    ],
    ids=["negative-start", "empty-span", "reversed", "past-the-end", "unknown-label", "one-bad-among-good"],
)
def test_unmaskable_findings_return_block_without_a_copy(make_client, entities):
    client = make_client(detector=FakeDetector(raw=entities))
    response = client.post("/api/check", json={"text": f"test {SECRET} text"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "operation_id": "WSQ-000001", "decision": "BLOCK", "reason": REASON_NOT_MASKED,
        "detected": [], "safe_text": None, "spans": [],
    }
    assert SECRET not in response.text
    item = client.get("/api/logs").json()["items"][0]
    assert (item["decision"], item["reason"], item["masking"]) == ("BLOCK", REASON_NOT_MASKED, "Not masked")


def test_block_safe_text_is_never_the_original(make_client):
    client = make_client(detector=FakeDetector((SECRET, "CREDITCARDNUMBER")))
    text = f"card {SECRET}"
    body = client.post("/api/check", json={"text": text}).json()
    assert body["decision"] == "BLOCK"
    assert body["safe_text"] != text and SECRET not in body["safe_text"]


def test_nothing_sensitive_is_logged(make_client, caplog):
    detector = FakeDetector(("Ahmed", "FIRSTNAME"), (SECRET, "CREDITCARDNUMBER"))
    client = make_client(detector=detector)
    with caplog.at_level(logging.DEBUG):
        body = client.post("/api/check", json={"text": f"Ahmed paid with {SECRET}"}).json()
        client.post("/api/check", json={"text": "clean text UNIQUEWORD"})
    assert body["decision"] == "BLOCK"
    for value in (SECRET, "Ahmed", "UNIQUEWORD", body["safe_text"]):
        assert value not in caplog.text


def test_detector_crash_does_not_leak_its_message(make_client, caplog):
    detector = FakeDetector(error=RuntimeError(f"model crashed on {SECRET}"))
    with caplog.at_level(logging.DEBUG):
        response = make_client(detector=detector).post("/api/check", json={"text": f"card {SECRET}"})
    assert assert_error(response, 503) == DETECTION_FAILED
    assert SECRET not in response.text
    assert SECRET not in caplog.text
    assert "RuntimeError" in caplog.text


def test_storage_failure_fails_closed(make_client, monkeypatch):
    client = make_client(detector=FakeDetector((SECRET, "CREDITCARDNUMBER")))

    def broken(*args, **kwargs):
        raise StorageError

    monkeypatch.setattr(client.app.state.audit_log, "record", broken)
    response = client.post("/api/check", json={"text": f"card {SECRET}"})
    assert assert_error(response, 503) == STORAGE_FAILED
    assert "safe_text" not in response.text and SECRET not in response.text


def test_chat_endpoint_is_gone(client):
    assert_error(client.post("/api/chat", json={"operation_id": "WSQ-000001", "safe_text": "x"}), 404)


def test_error_messages_refer_to_text_not_prompts():
    from backend.app import errors

    for name in ("DETECTION_UNAVAILABLE", "DETECTION_FAILED", "STORAGE_FAILED", "UNEXPECTED_ERROR"):
        message = getattr(errors, name)
        assert "prompt" not in message.lower() and "ai model" not in message.lower()


def test_reasons_match_the_contract():
    assert REASON_MASKED == "Sensitive data found, masked copy returned"
    assert REASON_CLEAN == "No sensitive data found"


def test_each_scan_gets_a_new_operation_id(make_client):
    client = make_client(detector=FakeDetector())
    ids = [client.post("/api/check", json={"text": "hello"}).json()["operation_id"] for _ in range(3)]
    assert ids == ["WSQ-000001", "WSQ-000002", "WSQ-000003"]


# ---------- CORS ----------

@pytest.mark.parametrize("origin", ["http://localhost:5500", "http://127.0.0.1:5500"])
def test_cors_allows_the_local_frontend(client, origin):
    response = client.options(
        "/api/check", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                               "Access-Control-Request-Headers": "content-type"}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ["http://evil.example", "null", "http://localhost:8080"])
def test_cors_rejects_other_origins(client, origin):
    response = client.options(
        "/api/check", headers={"Origin": origin, "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in response.headers
