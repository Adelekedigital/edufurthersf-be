from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse


def problem(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    errors: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://errors.edufurther.com/{code.lower()}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "instance": str(request.url),
    }
    if errors:
        body["errors"] = errors
    request_id = request.headers.get("x-request-id")
    if request_id:
        body["request_id"] = request_id[:128]
    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
        headers=dict(headers) if headers else None,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = {"fields": exc.errors()}
    return problem(
        request,
        status=422,
        code="VALIDATION_ERROR",
        title="Request validation failed",
        detail="One or more request fields are invalid.",
        errors=errors,
    )


_STATUS_CODES = {404: "NOT_FOUND", 429: "RATE_LIMIT_EXCEEDED"}


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    status = exc.status_code
    code = _STATUS_CODES.get(status, "REQUEST_FAILED")
    detail = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    # A rate limiter's own Retry-After (or any other header the raiser attached
    # to the HTTPException) must survive into the emitted response - `problem`
    # builds a fresh JSONResponse and would otherwise silently drop it, leaving
    # a 429 with no signal for how long a caller should actually wait.
    return problem(
        request,
        status=status,
        code=code,
        title="Request failed",
        detail=detail,
        headers=exc.headers,
    )
