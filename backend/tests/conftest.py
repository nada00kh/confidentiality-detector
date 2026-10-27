"""Shared test helpers.

Two kinds of tests use them:
  * mocked: FakeDetector (and fake model results in test_model_detector.py) exist only in the
    tests, to check how the API handles any detector output, including broken output;
  * real model: tests marked `real_model` use the actual checkpoint through the `real_model`
    fixture. It is loaded once per test run and the tests are skipped if it is not available.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.detection import Entity
from backend.app.main import create_app
from backend.app.model_detector import ModelDetector

# A recognizable value that must never appear in responses, logs or the database.
SECRET = "SECRET-4111-1111-1111-1111"
_UNSET = object()


class FakeDetector:
    """Finds each listed (value, label) pair wherever it occurs in the text.

    `raw` makes it return that exact object instead, to simulate a misbehaving detector.
    """

    def __init__(self, *values: tuple[str, str], error: Exception | None = None, raw=_UNSET):
        self.values = values
        self.error = error
        self.raw = raw
        self.calls = 0

    def detect(self, text: str):
        self.calls += 1
        if self.error:
            raise self.error
        if self.raw is not _UNSET:
            return self.raw
        entities = []
        for value, label in self.values:
            start = text.find(value)
            while start != -1:
                entities.append(Entity(start, start + len(value), label))
                start = text.find(value, start + 1)
        return entities


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "washq.sqlite3", timezone="Asia/Riyadh")


@pytest.fixture
def make_client(settings):
    def make(detector=None):
        return TestClient(create_app(settings, detector=detector))

    return make


@pytest.fixture
def client(make_client):
    """The app with no detector connected."""
    return make_client()


def pytest_configure(config):
    config.addinivalue_line("markers", "real_model: uses the actual downloaded checkpoint (slow; skipped if missing)")


@pytest.fixture(scope="session")
def real_model():
    """The real frozen detector, loaded once from WASHQ_MODEL_DIR / WASHQ_POLICY_PATH (or the defaults)."""
    settings = Settings()
    if not (settings.model_dir / "model.safetensors").is_file():
        pytest.skip(f"checkpoint not found in {settings.model_dir}")
    try:
        import confidentiality_detector.pipeline  # noqa: F401
    except ImportError:
        pytest.skip("the confidentiality_detector package is not installed in this environment")
    # A checkpoint that is present but does not load is an error, not a skip.
    return ModelDetector.load(settings.model_dir, settings.policy_path, device=settings.device)


def assert_error(response, status_code):
    assert response.status_code == status_code
    body = response.json()
    assert list(body) == ["detail"]
    assert isinstance(body["detail"], str) and body["detail"]
    return body["detail"]
