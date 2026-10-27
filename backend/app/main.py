import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import AfterValidator

from backend.app.config import Settings
from backend.app.detection import (
    CombinedDetector,
    DetectionFailedError,
    Detector,
    DetectorUnavailableError,
    MaskingFailedError,
)
from backend.app.detector_stub import UnavailableDetector
from backend.app.errors import (
    DETECTION_FAILED,
    DETECTION_UNAVAILABLE,
    STORAGE_FAILED,
    ErrorResponse,
    register_error_handlers,
)
from backend.app.model_detector import ModelDetector
from backend.app.saudi_rules import SaudiRuleDetector
from backend.app.sanitizer import detected_summary, sanitize, utf16_offset
from backend.app.schemas import (
    MAX_TEXT_LENGTH,
    CheckRequest,
    CheckResponse,
    Decision,
    LogsResponse,
    SpanOut,
    StatsResponse,
    known_type_code,
)
from backend.app.storage import (
    MASKING_NOT_MASKED,
    REASON_CLEAN,
    REASON_MASKED,
    REASON_NOT_MASKED,
    AuditLog,
    masking_text,
)

logger = logging.getLogger("washq")

router = APIRouter()


def error_docs(*pairs: tuple[int, str]) -> dict:
    return {status: {"model": ErrorResponse, "description": text} for status, text in pairs}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/api/check",
    responses=error_docs(
        (422, "The request is not valid."),
        (503, f"{DETECTION_UNAVAILABLE} / {DETECTION_FAILED} / {STORAGE_FAILED}"),
    ),
)
def check(body: CheckRequest, request: Request) -> CheckResponse:
    state = request.app.state
    text = body.text

    # Fail closed: if the detector can't give a trustworthy answer, the scan fails (503)
    # and no text is returned, because we don't know whether the text is sensitive.
    try:
        result = sanitize(text, list(state.detector.detect(text)))
    except (DetectorUnavailableError, DetectionFailedError):
        raise
    except MaskingFailedError:
        # The detector found something but it can't be masked: BLOCK without a masked copy.
        logger.warning("Masking failed; returning BLOCK without a masked copy")
        operation_id = state.audit_log.record("BLOCK", REASON_NOT_MASKED, MASKING_NOT_MASKED, {}, utc_now())
        return CheckResponse(
            operation_id=operation_id, decision="BLOCK", reason=REASON_NOT_MASKED,
            detected=[], safe_text=None, spans=[],
        )
    except Exception as exc:
        # Only the error type is logged: the message could contain parts of the text.
        logger.error("Detector failed: %s", type(exc).__name__)
        raise DetectionFailedError from None

    # ALLOW = nothing sensitive, the original can be shared as it is.
    # BLOCK = sensitive data found, the original must not be shared; the masked copy is returned instead.
    masked = sum(result.counts.values())
    if masked:
        decision, reason, safe_text = "BLOCK", REASON_MASKED, result.safe_text
    else:
        decision, reason, safe_text = "ALLOW", REASON_CLEAN, text
    operation_id = state.audit_log.record(decision, reason, masking_text(masked), result.counts, utc_now())

    return CheckResponse(
        operation_id=operation_id,
        decision=decision,
        reason=reason,
        detected=detected_summary(result.counts),
        safe_text=safe_text,
        spans=[
            SpanOut(start=utf16_offset(text, s.start), end=utf16_offset(text, s.end), type=s.type)
            for s in result.spans
        ],
    )


@router.get("/api/stats", responses=error_docs((422, "The request is not valid."), (503, STORAGE_FAILED)))
def stats(request: Request, days: Annotated[int, Query(ge=1, le=90)] = 7) -> StatsResponse:
    return StatsResponse(**request.app.state.audit_log.stats(utc_now(), days))


@router.get("/api/logs", responses=error_docs((422, "The request is not valid."), (503, STORAGE_FAILED)))
def logs(
    request: Request,
    decision: Decision | None = None,
    type: Annotated[str | None, Query(max_length=32), AfterValidator(known_type_code)] = None,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    q: Annotated[str | None, Query(max_length=20)] = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
) -> LogsResponse:
    result = request.app.state.audit_log.logs(
        utc_now(),
        days=days,
        decision=decision,
        type_code=type,
        q=(q or "").strip() or None,
        page=page,
        page_size=page_size,
    )
    return LogsResponse(**result)


def build_detector(settings: Settings) -> Detector:
    """The real detector: the frozen model + rules v3, together with the Saudi rules."""
    model = ModelDetector.load(settings.model_dir, settings.policy_path, device=settings.device)
    return CombinedDetector(model, SaudiRuleDetector())


def load_detector(factory: Callable[[Settings], Detector], settings: Settings) -> Detector:
    """Build the detector once; if that fails, scans answer 503 instead of ever answering ALLOW."""
    try:
        detector = factory(settings)
    except Exception as exc:
        # Start-up errors carry no scanned text, only paths and file problems.
        logger.error("Detector could not be loaded (%s: %s); /api/check will answer 503", type(exc).__name__, exc)
        return UnavailableDetector()
    logger.info("Detector loaded")
    return detector


def create_app(
    settings: Settings | None = None,
    detector: Detector | None = None,
    detector_factory: Callable[[Settings], Detector] | None = None,
) -> FastAPI:
    """detector: use this detector. detector_factory: build the detector once at start-up.

    With neither, every scan answers 503.
    """
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # The server accepts requests only after this, so no scan runs before the model is loaded.
        if detector_factory is not None:
            app.state.detector = load_detector(detector_factory, settings)
        yield

    app = FastAPI(title="WASHQ API", lifespan=lifespan)
    app.state.settings = settings
    app.state.detector = detector or UnavailableDetector()
    app.state.audit_log = AuditLog(settings.db_path, settings.timezone)

    register_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )
    app.include_router(router)
    return app


app = create_app(detector_factory=build_detector)

__all__ = ["MAX_TEXT_LENGTH", "app", "create_app"]
