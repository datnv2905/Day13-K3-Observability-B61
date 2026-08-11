from __future__ import annotations

import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        clear_contextvars()

        correlation_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:8]}"

        bind_contextvars(correlation_id=correlation_id)

        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        # Handler đọc mốc này để đo trọn thời gian request nằm trong server, gồm cả
        # thời gian chờ hàng đợi. Bấm giờ bên trong agent sẽ bỏ sót phần chờ đó.
        request.state.started = start
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        response.headers["x-request-id"] = correlation_id
        response.headers["x-response-time-ms"] = f"{elapsed_ms:.1f}"

        return response
