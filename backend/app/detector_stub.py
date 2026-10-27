"""The detector create_app() uses when no real detector is passed in.

It refuses every request: it never looks at the text and never returns any entities,
so the API cannot claim that a text was checked. main.py passes the real detector.
"""

from typing import NoReturn

from backend.app.detection import DetectorUnavailableError


class UnavailableDetector:
    def detect(self, text: str) -> NoReturn:
        raise DetectorUnavailableError
