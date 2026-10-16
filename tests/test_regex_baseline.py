from src.detectors.regex_detector import (
    detect_entities,
    classify_message
)

def test_email_detection():

    text = "Email: test@example.com"

    result = detect_entities(text)
# assert is useed to ensure one condition is true, if false it triggers Assertion Error 
# we wrote these lines to make sure the extracted value matches the test value
# we test two things: if entity type is correct and if extracted value is correct
    assert len(result) == 1
    assert result[0]["label"] == "private_email"
    assert result[0]["text"] == "test@example.com"

def test_arabic_phone():
    text = "رقم الهاتف: 0551234567"

    result = detect_entities(text)

    assert len(result) == 1
    assert result[0]["label"] == "private_phone"

    # Ensure the original character offsets are correct
    entity = result[0]
    # to ensure if normalization works in phone numbers
    assert text[entity["start"]:entity["end"]] == entity["text"]
    # to ensure that offsets is correct
    assert entity["start"] == 12
    assert entity["end"] == 22

def test_multiple_entities():
    text = "راسلوني على 0505283502 او test@example.com"

    result = detect_entities(text)

    labels = {entity["label"] for entity in result} # i suggest to change set to list 

    assert labels == {"private_email", "private_phone"}

def test_safe_message():
    text = "السلام عليكم كيف الحال؟"

    assert detect_entities(text) == []
    assert classify_message(text) == "ALLOW"

def test_sensitive_message():
    text = "بريدي test@example.com"

    assert classify_message(text) == "BLOCK"

   



