"""Request and response shapes, matching the frontend's API_CONTRACT.md."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from backend.app.labels import TYPE_LABELS

MAX_TEXT_LENGTH = 10_000

Decision = Literal["ALLOW", "BLOCK"]


def known_type_code(value: str | None) -> str | None:
    if value is not None and value not in TYPE_LABELS:
        raise PydanticCustomError("unknown_type", "Unknown data type.")
    return value


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- POST /api/check ----------

class CheckRequest(StrictRequest):
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)

    @field_validator("text")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        # The text itself is not changed: detection spans must match what the client sent.
        if not value.strip():
            raise PydanticCustomError("blank_text", "Text must not be blank.")
        return value


class DetectedType(BaseModel):
    type: str
    label: str
    count: int


class SpanOut(BaseModel):
    start: int
    end: int
    type: str


class CheckResponse(BaseModel):
    operation_id: str
    decision: Decision
    reason: str
    detected: list[DetectedType]
    safe_text: str | None
    spans: list[SpanOut]


# ---------- GET /api/logs and GET /api/stats ----------

class LogItem(BaseModel):
    operation_id: str
    time: str
    detected: list[DetectedType]
    decision: Decision
    reason: str
    masking: str


class LogsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[LogItem]


class DailyCount(BaseModel):
    date: str
    allow: int
    block: int


class StatsResponse(BaseModel):
    days: int
    total: int
    allowed: int
    blocked: int
    daily: list[DailyCount]
    top_types: list[DetectedType]
    latest: list[LogItem]
