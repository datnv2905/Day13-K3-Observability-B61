from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars

from .pii import scrub_text
from .timeutil import now_local

LOG_PATH = Path(os.getenv("LOG_PATH", "data/logs.jsonl"))


class JsonlFileProcessor:
    def __call__(self, logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        rendered = structlog.processors.JSONRenderer()(logger, method_name, event_dict)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(rendered + "\n")
        return event_dict



def add_local_timestamp(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Ghi `ts` theo giờ Việt Nam, kèm offset +07:00 để mốc thời gian không mơ hồ.

    Thay cho `structlog.processors.TimeStamper(utc=True)` vì TimeStamper chỉ chọn được
    UTC hoặc giờ máy dạng naive, không gắn được offset cụ thể.
    """
    event_dict["ts"] = now_local().isoformat(timespec="microseconds")
    return event_dict


def _scrub_value(value: Any) -> Any:
    """Recursively redact text before an event is serialized to JSON."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {key: _scrub_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_value(item) for item in value)
    return value


def scrub_event(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return {key: _scrub_value(value) for key, value in event_dict.items()}



def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")))
    structlog.configure(
        processors=[
            merge_contextvars,
            structlog.processors.add_log_level,
            add_local_timestamp,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            scrub_event,
            JsonlFileProcessor(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )



def get_logger() -> structlog.typing.FilteringBoundLogger:
    return structlog.get_logger()
