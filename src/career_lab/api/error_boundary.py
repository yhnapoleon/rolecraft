"""Safe HTTP failures and request diagnostics with an explicit field whitelist."""

import json
import logging
import re
from importlib.metadata import version
from logging.config import dictConfig
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

LOGGER = logging.getLogger("career_lab.http")
CODE_VERSION = version("career-lab")
METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}
)


def request_fields(request: Request, status: int) -> dict[str, object]:
    """Only server metadata: no raw path, query, headers, body, identity or exception text."""
    return {
        "request_id": request.state.server_request_id,
        "method": request.method if request.method in METHODS else "OTHER",
        "route": getattr(request.scope.get("route"), "path", "<unmatched>"),
        "status": status,
        "code": getattr(request.state, "safe_error_code", "ok" if status < 400 else "http_error"),
        "code_version": CODE_VERSION,
    }


def log_failure(request: Request, error: Exception, status: int, code: str) -> None:
    # Codes are server classifications; reject malformed values instead of logging free text.
    request.state.safe_error_code = (
        code if re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code) else "http_error"
    )
    LOGGER.log(
        logging.ERROR if status >= 500 else logging.WARNING,
        json.dumps(
            {
                **request_fields(request, status),
                "event": "internal_failure" if status >= 500 else "request_rejected",
                "error_type": type(error).__name__,
            },
            sort_keys=True,
        ),
    )


def internal_error(request: Request, error: Exception) -> JSONResponse:
    log_failure(request, error, 500, "internal_error")
    return JSONResponse(
        {"error": "internal server error", "code": "internal_error"}, status_code=500
    )


class SafeHttpBoundary(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.server_request_id = uuid4().hex
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception as error:
            # Catch before Starlette's server-error layer rethrows to an unsafe server traceback.
            response = internal_error(request, error)
        LOGGER.info(
            json.dumps(
                {
                    **request_fields(request, response.status_code),
                    "event": "request_completed",
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                },
                sort_keys=True,
            )
        )
        return response


def install_safe_logging(app: FastAPI) -> None:
    app.add_middleware(SafeHttpBoundary)


class SafeServerErrorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Ignore message, args and traceback: startup errors can contain local configuration.
        return "HTTP server error; check the configured host and port."


def configure_http_logging() -> None:
    """Keep loggers enabled; only owned HTTP and safe server diagnostics may emit."""
    for logger in tuple(logging.Logger.manager.loggerDict.values()):
        if isinstance(logger, logging.Logger):
            logger.handlers.clear()
            logger.propagate = True
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "message": {"format": "%(message)s"},
                "server_error": {"()": SafeServerErrorFormatter},
            },
            "handlers": {
                "safe_http": {"class": "logging.StreamHandler", "formatter": "message"},
                "discard": {"class": "logging.NullHandler"},
                "safe_server_error": {
                    "class": "logging.StreamHandler",
                    "level": "ERROR",
                    "formatter": "server_error",
                },
            },
            "root": {"level": "WARNING", "handlers": ["discard"]},
            "loggers": {
                "career_lab.http": {
                    "level": "INFO",
                    "handlers": ["safe_http"],
                    "propagate": False,
                },
                "uvicorn.error": {
                    "level": "ERROR",
                    "handlers": ["safe_server_error"],
                    "propagate": False,
                },
            },
        }
    )
