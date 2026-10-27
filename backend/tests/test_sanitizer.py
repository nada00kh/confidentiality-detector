import itertools
import json

import pytest

from backend.app.config import Settings
from backend.app.detection import DetectionFailedError, Entity, MaskingFailedError
from backend.app.labels import LABEL_PRIORITY, LABEL_TO_CODE, MODEL_LABEL_TO_CODE, SAUDI_LABEL_TO_CODE, TYPE_LABELS
from backend.app.sanitizer import Span, sanitize, utf16_offset


# ---------- label mapping ----------

def test_every_detector_label_maps_to_a_known_type():
    assert set(LABEL_TO_CODE.values()) <= set(TYPE_LABELS)


def test_saudi_labels_match_the_saudi_rules():
    from backend.app.saudi_rules import PATTERNS

    assert set(SAUDI_LABEL_TO_CODE) == set(PATTERNS)


def test_model_labels_match_the_frozen_detector():
    from confidentiality_detector.labels import BIO_LABELS, TARGET_LABELS

    assert set(MODEL_LABEL_TO_CODE) == set(TARGET_LABELS)
    # Every BIO tag of the model reduces to a mapped label; there is no unmapped model label.
    assert {tag[2:] for tag in BIO_LABELS if tag != "O"} == set(MODEL_LABEL_TO_CODE)


def test_model_labels_match_the_downloaded_checkpoint():
    config_path = Settings().model_dir / "config.json"
    if not config_path.is_file():
        pytest.skip(f"checkpoint not found in {config_path.parent}")
    id2label = json.loads(config_path.read_text(encoding="utf-8"))["id2label"]
    tags = set(id2label.values()) - {"O"}
    assert all(tag[:2] in ("B-", "I-") for tag in tags)
    assert {tag[2:] for tag in tags} == set(MODEL_LABEL_TO_CODE)


def test_us_ssn_is_masked_as_ssn_not_national_id():
    result = sanitize("SSN 123-45-6789", [Entity(4, 15, "SSN")])
    assert result.safe_text == "SSN [SSN]"


def test_ssn_is_its_own_type():
    assert MODEL_LABEL_TO_CODE["SSN"] == "SSN"
    assert TYPE_LABELS["SSN"] == "Social Security number"
    assert SAUDI_LABEL_TO_CODE["national_id"] == "NATIONAL_ID"
    assert SAUDI_LABEL_TO_CODE["iqama"] == "IQAMA"


def test_contract_codes_keep_their_labels():
    assert {code: TYPE_LABELS[code] for code in (
        "PERSON_NAME", "NATIONAL_ID", "PHONE", "EMAIL", "IBAN", "CARD_NUMBER", "PASSWORD", "CONFIDENTIAL"
    )} == {
        "PERSON_NAME": "Person name", "NATIONAL_ID": "National ID", "PHONE": "Phone number",
        "EMAIL": "Email address", "IBAN": "IBAN", "CARD_NUMBER": "Card number", "PASSWORD": "Password",
        "CONFIDENTIAL": "Confidential topic",
    }


# ---------- merging, priority and duplicates ----------

@pytest.mark.parametrize("saudi_label, code", [("national_id", "NATIONAL_ID"), ("iqama", "IQAMA"),
                                               ("private_phone", "PHONE")])
def test_saudi_label_wins_over_model_accountnumber_on_the_same_value(saudi_label, code):
    text = "ID 1098765432 end"
    for entities in itertools.permutations([Entity(3, 13, "ACCOUNTNUMBER"), Entity(3, 13, saudi_label)]):
        result = sanitize(text, list(entities))
        assert result.safe_text == f"ID [{code}] end"
        assert result.counts == {code: 1}


def test_saudi_label_wins_even_when_the_model_span_is_longer():
    # The model's span runs past the value; everything stays masked, typed by the Saudi rule.
    text = "ID 1098765432, end"
    result = sanitize(text, [Entity(3, 14, "ACCOUNTNUMBER"), Entity(3, 13, "national_id")])
    assert result.safe_text == "ID [NATIONAL_ID] end"
    assert result.spans == [Span(3, 14, "NATIONAL_ID")]


def test_same_value_from_two_detectors_is_masked_once():
    text = "mail a@b.co now"
    result = sanitize(text, [Entity(5, 11, "EMAIL"), Entity(5, 11, "private_email")])
    assert result.safe_text == "mail [EMAIL] now"
    assert result.counts == {"EMAIL": 1}


def test_merge_result_does_not_depend_on_detector_order():
    entities = [Entity(0, 10, "CREDITCARDNUMBER"), Entity(0, 10, "ACCOUNTNUMBER"), Entity(5, 12, "IBAN"),
                Entity(20, 30, "PHONENUMBER"), Entity(20, 30, "private_phone"), Entity(32, 36, "PASSWORD")]
    text = "-" * 40  # no word characters, so no span is widened
    results = {tuple(sanitize(text, list(order)).spans) for order in itertools.permutations(entities)}
    assert results == {(Span(0, 12, "ACCOUNT_NUMBER"), Span(20, 30, "PHONE"), Span(32, 36, "PASSWORD"))}


def test_type_is_chosen_by_the_length_detected_not_the_widened_length():
    # The account span cuts into the card number's word; widening makes it look longer.
    text = "card 4111111111111111x end"
    result = sanitize(text, [Entity(5, 21, "CREDITCARDNUMBER"), Entity(18, 22, "ACCOUNTNUMBER")])
    assert result.safe_text == "card [CARD_NUMBER] end"


def test_chained_overlaps_become_one_span():
    text = "-" * 16
    result = sanitize(text, [Entity(0, 5, "FIRSTNAME"), Entity(4, 9, "LASTNAME"), Entity(8, 12, "LASTNAME")])
    assert result.spans == [Span(0, 12, "PERSON_NAME")]
    assert result.safe_text == "[PERSON_NAME]----"


def test_model_labels_have_no_priority():
    assert all(LABEL_PRIORITY.get(label, 0) == 0 for label in MODEL_LABEL_TO_CODE)
    assert all(LABEL_PRIORITY[label] > 0 for label in SAUDI_LABEL_TO_CODE)


# ---------- masking ----------


def test_no_entities_leaves_the_text_unchanged():
    result = sanitize("nothing here", [])
    assert result.safe_text == "nothing here"
    assert result.spans == [] and result.counts == {}


def test_entities_are_masked_in_text_order_regardless_of_input_order():
    text = "mail a@b.co or call 0551234567"
    result = sanitize(text, [Entity(20, 30, "PHONENUMBER"), Entity(5, 11, "EMAIL")])
    assert result.safe_text == "mail [EMAIL] or call [PHONE]"
    assert result.spans == [Span(5, 11, "EMAIL"), Span(20, 30, "PHONE")]
    assert list(result.counts) == ["EMAIL", "PHONE"]


def test_overlapping_entities_are_merged_so_everything_is_masked():
    text = "card 4111111111111111 end"
    result = sanitize(text, [Entity(5, 21, "CREDITCARDNUMBER"), Entity(15, 25, "ACCOUNTNUMBER")])
    assert result.safe_text == "card [CARD_NUMBER]"
    assert result.spans == [Span(5, 25, "CARD_NUMBER")]


def test_duplicate_entities_are_counted_once():
    result = sanitize("pw: hunter2", [Entity(4, 11, "PASSWORD"), Entity(4, 11, "PASSWORD")])
    assert result.safe_text == "pw: [PASSWORD]"
    assert result.counts == {"PASSWORD": 1}


def test_adjacent_entities_stay_separate():
    text = "x@y.co+966551234567"
    result = sanitize(text, [Entity(0, 6, "EMAIL"), Entity(6, 19, "PHONENUMBER")])
    assert result.safe_text == "[EMAIL][PHONE]"
    assert result.counts == {"EMAIL": 1, "PHONE": 1}


def test_two_spans_inside_one_word_become_one():
    result = sanitize("AhmedAli", [Entity(0, 5, "FIRSTNAME"), Entity(5, 8, "LASTNAME")])
    assert result.safe_text == "[PERSON_NAME]"
    assert result.counts == {"PERSON_NAME": 1}


# ---------- a span that cuts a word is widened to the whole word ----------

def test_partial_mask_of_an_id_attached_to_an_arabic_word_covers_the_whole_word():
    # Seen with the real model: only part of the ID was flagged, leaving "10" visible.
    text = "هويتي1098765432"
    result = sanitize(text, [Entity(7, 15, "ACCOUNTNUMBER")])
    assert result.safe_text == "[ACCOUNT_NUMBER]"
    assert result.spans == [Span(0, 15, "ACCOUNT_NUMBER")]


def test_partial_mask_inside_an_arabic_word_covers_the_whole_word():
    text = "العميل أحمد"
    result = sanitize(text, [Entity(2, 6, "FIRSTNAME"), Entity(7, 11, "FIRSTNAME")])
    assert result.safe_text == "[PERSON_NAME] [PERSON_NAME]"


def test_arabic_diacritics_count_as_part_of_the_word():
    text = "السيد مُحَمَّد هنا"
    start = text.index("مُحَمَّد")
    result = sanitize(text, [Entity(start + 2, start + 4, "FIRSTNAME")])
    assert result.safe_text == "السيد [PERSON_NAME] هنا"


@pytest.mark.parametrize(
    "text, entity, expected",
    [
        ("call Mira Okafor, please", Entity(10, 16, "LASTNAME"), "call Mira [PERSON_NAME], please"),
        ("mail a.b@c.co.", Entity(5, 13, "EMAIL"), "mail [EMAIL]."),
        ("pw: Zq81kLm!x end", Entity(4, 13, "PASSWORD"), "pw: [PASSWORD] end"),
        ("(555-0142)", Entity(1, 9, "PHONENUMBER"), "([PHONE])"),
    ],
    ids=["comma-after-name", "full-stop-after-email", "symbol-inside-password", "brackets"],
)
def test_spans_on_word_boundaries_are_not_widened(text, entity, expected):
    assert sanitize(text, [entity]).safe_text == expected


def test_arabic_text_is_masked_by_character_position():
    text = "اتصل بأحمد على 0551234567"
    start = text.index("0551234567")
    result = sanitize(text, [Entity(start, start + 10, "PHONENUMBER")])
    assert result.safe_text == "اتصل بأحمد على [PHONE]"


@pytest.mark.parametrize(
    "entity",
    [Entity(-1, 2, "EMAIL"), Entity(2, 2, "EMAIL"), Entity(3, 1, "EMAIL"), Entity(0, 99, "EMAIL"),
     Entity(0, 2, "NOT_A_LABEL"), Entity(0, 2, "email"), Entity("0", 2, "EMAIL"), Entity(0.0, 2, "EMAIL")],
)
def test_unmaskable_entities_raise_masking_failed(entity):
    with pytest.raises(MaskingFailedError):
        sanitize("some text", [entity])


@pytest.mark.parametrize("item", [None, "EMAIL", (0, 2, "EMAIL"), {"start": 0, "end": 2, "label": "EMAIL"}])
def test_output_that_is_not_entities_raises_detection_failed(item):
    with pytest.raises(DetectionFailedError):
        sanitize("some text", [Entity(0, 2, "EMAIL"), item])


def test_utf16_offset():
    text = "a😀b"
    assert [utf16_offset(text, i) for i in range(4)] == [0, 1, 3, 4]
    assert utf16_offset("بسم", 3) == 3
