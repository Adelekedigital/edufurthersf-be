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
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")


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


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    status = exc.status_code
    code = "NOT_FOUND" if status == 404 else "REQUEST_FAILED"
    detail = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    return problem(request, status=status, code=code, title="Request failed", detail=detail)
