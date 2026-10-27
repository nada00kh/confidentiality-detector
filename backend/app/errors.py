"""Error responses for the WASHQ API.

Every error is returned as {"detail": "<one readable sentence>"}, the shape the frontend
expects. Error responses never include the submitted values, because they may contain
the sensitive data WASHQ exists to protect.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.app.detection import DetectionFailedError, DetectorUnavailableError
from backend.app.storage import StorageError


class ErrorResponse(BaseModel):
    detail: str


DETECTION_UNAVAILABLE = "Detection is not available right now, so the text was not checked or masked."
DETECTION_FAILED = "Detection failed, so the text was not masked. Please try again."
STORAGE_FAILED = "The scan could not be recorded, so no result was returned. Please try again."
UNEXPECTED_ERROR = "Something went wrong on the server."

INVALID_VALUE_TYPES = {
    "literal_error", "enum", "int_parsing", "int_type", "int_from_float",
    "greater_than", "greater_than_equal", "less_than", "less_than_equal", "unknown_type",
}


def validation_message(error: dict) -> str:
    """Turn one Pydantic error into a sentence without the submitted value.

    Only names that come from our own schema (the "loc" of missing or wrongly typed
    fields) are used. Names of unexpected fields come from the client, so they are
    never repeated.
    """
    kind = error.get("type")
    loc = error.get("loc", ())
    field = loc[-1] if len(loc) > 1 and isinstance(loc[-1], str) else None

    if kind == "json_invalid":
        return "The request body is not valid JSON."
    if kind in ("model_attributes_type", "dict_type", "model_type"):
        return "The request body must be a JSON object."
    if kind == "extra_forbidden":
        return "The request contains fields that are not allowed."
    if field is None:
        return "The request body is missing or not valid."
    if kind == "missing":
        return f'The "{field}" field is required.'
    if kind == "string_type":
        return f'The "{field}" field must be a string.'
    if kind in ("string_too_short", "blank_text"):
        return f'The "{field}" field must not be empty.'
    if kind == "string_too_long":
        limit = error.get("ctx", {}).get("max_length")
        if isinstance(limit, int):
            return f'The "{field}" field is too long (maximum {limit:,} characters).'
        return f'The "{field}" field is too long.'
    if kind in INVALID_VALUE_TYPES:
        return f'The "{field}" value is not valid.'
    return "The request is not valid."


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    message = validation_message(errors[0]) if errors else "The request is not valid."
    return JSONResponse(status_code=422, content={"detail": message})


def _respond(status_code: int, detail: str):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": detail})

    return handler


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(DetectorUnavailableError, _respond(503, DETECTION_UNAVAILABLE))
    app.add_exception_handler(DetectionFailedError, _respond(503, DETECTION_FAILED))
    app.add_exception_handler(StorageError, _respond(503, STORAGE_FAILED))
    app.add_exception_handler(Exception, _respond(500, UNEXPECTED_ERROR))
