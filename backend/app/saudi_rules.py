"""Saudi formats that the English-trained model does not know: email, Saudi mobile numbers,
national ID and Iqama numbers, also when written with Arabic-Indic or Persian digits.

DEMO-ONLY EXTENSION. These rules are not part of the evaluated system (frozen R3 + rules v3,
strict): they were never evaluated, and Challenge v2 did not include them. Their findings are
supplemental: they can add masked values (and turn ALLOW into BLOCK), but where they overlap a
finding of the core detector, the core finding's type is kept (labels.LABEL_PRIORITY).

Origin: the team's regex baseline, src/detectors/regex_detector.py in commit 142f268
(deleted from the repository in e93b2cd). DIGIT_MAP, PATTERNS and the overlap handling are
copied unchanged so that detection behaves exactly as before; only the matched value is no
longer returned, because the API needs positions and labels only.
"""

import re

from backend.app.detection import Entity

# Convert Arabic-Indic and Persian digits to ASCII digits. Every character maps to exactly
# one character, so positions in the converted text are positions in the original text.
DIGIT_MAP = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789"
)

PATTERNS = {
    "private_email": re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])"),
    "private_phone": re.compile(r"(?<![\w+])(?:\+966|00966|0)5(?:[\s-]?[0-9]){8}(?!\w)"),
    "national_id": re.compile(r"(?<!\w)1[0-9]{9}(?!\w)"),
    "iqama": re.compile(r"(?<!\w)2[0-9]{9}(?!\w)"),
}


def detect_entities(text: str) -> list[dict]:
    """Matches as {"label", "start", "end"}, earlier and longer matches first, without overlaps."""
    normalized = text.translate(DIGIT_MAP)
    matches = [
        {"label": label, "start": match.start(), "end": match.end()}
        for label, pattern in PATTERNS.items()
        for match in pattern.finditer(normalized)
    ]
    matches.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))

    results = []
    for item in matches:
        if not any(item["start"] < old["end"] and old["start"] < item["end"] for old in results):
            results.append(item)
    return results


class SaudiRuleDetector:
    def detect(self, text: str) -> list[Entity]:
        return [Entity(item["start"], item["end"], item["label"]) for item in detect_entities(text)]
