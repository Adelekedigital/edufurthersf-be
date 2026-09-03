import logging
from time import perf_counter

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import database_ready, router
from app.core.config import get_settings
from app.core.errors import http_exception_handler, problem, validation_exception_handler
from app.core.observability import configure_logging, new_request_id, request_duration
from app.core.sentry import initialize_sentry
from app.infra.db import get_db

settings = get_settings()
configure_logging()
initialize_sentry(
    settings.sentry_dsn,
    settings.environment,
    settings.app_version,
    settings.sentry_traces_sample_rate,
)
logger = logging.getLogger("app.http")
app = FastAPI(title="Edufurther Scholarship Finder", version=settings.app_version)
app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
app.include_router(router, prefix="/api/v1")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "")[:128] or new_request_id()
    request.state.request_id = request_id
    started = perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    logger.info(
        "http_request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "duration_ms": request_duration(started),
            "status_code": response.status_code,
        },
    )
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}


@app.get("/ready")
async def ready(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await database_ready(db)
    except Exception:
        return problem(
            request,
            status=503,
            code="DEPENDENCY_NOT_READY",
            title="Dependency not ready",
            detail="The scholarship database is not available.",
        )
    return {"status": "ready"}
