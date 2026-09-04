"""Request correlation and metadata-only API failure logging."""

import logging
import re
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

LOGGER = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def request_id_from_header(value: str | None) -> str:
    candidate = (value or "").strip()
    if REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return str(uuid4())


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Attach a safe request ID and log failures without bodies or headers."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request_id_from_header(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        log_fields = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        }
        handled_unexpected_error = False
        try:
            response = await call_next(request)
        except Exception:
            handled_unexpected_error = True
            LOGGER.error(
                "Unhandled API request failure",
                extra={**log_fields, "status_code": 500},
            )
            response = JSONResponse(
                {"detail": "Internal server error"},
                status_code=500,
            )

        response.headers["X-Request-ID"] = request_id
        if response.status_code >= 400 and not handled_unexpected_error:
            LOGGER.error(
                "API request failed",
                extra={**log_fields, "status_code": response.status_code},
            )
        return response
