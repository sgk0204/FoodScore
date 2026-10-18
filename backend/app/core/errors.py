"""RFC 9457 Problem Details for every error response (guide §8.3)."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

ERROR_BASE = "https://foodscore.app/errors/"
PROBLEM_JSON = "application/problem+json"
log = structlog.get_logger(__name__)


class AppError(Exception):
    """Raise anywhere; rendered as application/problem+json."""

    def __init__(
        self,
        status: int,
        slug: str,
        title: str,
        detail: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.slug = slug
        self.title = title
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra

    def to_problem(self, request_id: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": ERROR_BASE + self.slug,
            "title": self.title,
            "status": self.status,
        }
        if self.detail:
            body["detail"] = self.detail
        body.update(self.extra)
        body["request_id"] = request_id
        return body


# Common errors -----------------------------------------------------------------------


def unauthorized(detail: str = "Authentication required") -> AppError:
    return AppError(
        401, "unauthorized", "Unauthorized", detail, headers={"WWW-Authenticate": "Bearer"}
    )


def not_found(what: str = "Resource") -> AppError:
    # Same response for "missing" and "not yours" so ids cannot be probed (IDOR).
    return AppError(404, "not-found", f"{what} not found")


def rate_limited(retry_after: int, detail: str = "Too many requests") -> AppError:
    return AppError(
        429, "rate-limited", "Too Many Requests", detail, headers={"Retry-After": str(retry_after)}
    )


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _problem(
    status: int, body: dict[str, Any], headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return _problem(exc.status, exc.to_problem(_request_id(request)), exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        slug = {404: "not-found", 405: "method-not-allowed", 401: "unauthorized"}.get(
            exc.status_code, "http-error"
        )
        body = {
            "type": ERROR_BASE + slug,
            "title": str(exc.detail) if exc.detail else "HTTP error",
            "status": exc.status_code,
            "request_id": _request_id(request),
        }
        return _problem(exc.status_code, body, getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        body = {
            "type": ERROR_BASE + "validation-error",
            "title": "Request validation failed",
            "status": 422,
            "errors": errors,
            "request_id": _request_id(request),
        }
        return _problem(422, body)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        body = {
            "type": ERROR_BASE + "internal",
            "title": "Something went wrong",
            "status": 500,
            "request_id": _request_id(request),
        }
        return _problem(500, body)
