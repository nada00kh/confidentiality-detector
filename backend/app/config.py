"""Backend settings, read from environment variables with safe local defaults."""

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

DEFAULT_CORS_ORIGINS = ("http://localhost:5500", "http://127.0.0.1:5500")


def _origins_from_env() -> tuple[str, ...]:
    value = os.environ.get("WASHQ_CORS_ORIGINS")
    if value is None:
        return DEFAULT_CORS_ORIGINS
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


@dataclass(frozen=True)
class Settings:
    # SQLite file for the audit log (operation metadata only, never the scanned text).
    db_path: Path = field(
        default_factory=lambda: Path(os.environ.get("WASHQ_DB_PATH", BACKEND_DIR / "data" / "washq.sqlite3"))
    )
    # Time zone used to group the dashboard's daily numbers.
    timezone: str = field(default_factory=lambda: os.environ.get("WASHQ_TIMEZONE", "Asia/Riyadh"))
    # Browser origins allowed to call the API (the local frontend during development).
    cors_origins: tuple[str, ...] = field(default_factory=_origins_from_env)
    # The frozen detector (docs/INTEGRATION.md): local checkpoint folder and policy file.
    model_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("WASHQ_MODEL_DIR", REPO_DIR / "checkpoints" / "r2_e3b_positive"))
    )
    policy_path: Path = field(
        default_factory=lambda: Path(os.environ.get("WASHQ_POLICY_PATH", REPO_DIR / "configs" / "inference" / "policy.json"))
    )
    # "cpu" is the configuration the detector was evaluated with.
    device: str = field(default_factory=lambda: os.environ.get("WASHQ_DEVICE", "cpu"))
