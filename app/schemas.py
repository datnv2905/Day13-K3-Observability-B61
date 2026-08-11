from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .timeutil import now_local


class ChatRequest(BaseModel):
    user_id: str = Field(..., examples=["u_team_01"])
    session_id: str = Field(..., examples=["s_demo_01"])
    feature: str = Field(default="qa", examples=["qa", "summary"])
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    answer: str
    correlation_id: str
    # latency_ms: tổng thời gian trong server, đo từ mốc middleware — đây là thứ người
    # dùng cảm nhận và là SLI cho SLO/alert.
    # agent_latency_ms: riêng phần agent xử lý; hiệu hai số là thời gian xếp hàng.
    latency_ms: int
    agent_latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    quality_score: float


class LogRecord(BaseModel):
    ts: datetime = Field(default_factory=now_local)
    level: Literal["info", "warning", "error", "critical"]
    service: str
    event: str
    correlation_id: str
    env: str
    user_id_hash: str | None = None
    session_id: str | None = None
    feature: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    agent_latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    error_type: str | None = None
    tool_name: str | None = None
    payload: dict[str, Any] | None = None
