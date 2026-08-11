from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from .pii import scrub_text

try:
    from langfuse import Langfuse, get_client, observe

    LANGFUSE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - chỉ dùng khi chưa cài requirements
    LANGFUSE_SDK_AVAILABLE = False

    def observe(*args: Any, **kwargs: Any):
        def decorator(func):
            return func

        return decorator

    class _DummyClient:
        def update_current_trace(self, **kwargs: Any) -> None:
            return None

        def update_current_generation(self, **kwargs: Any) -> None:
            return None

    def get_client():
        return _DummyClient()

    Langfuse = None  # type: ignore[assignment]


def mask_pii(*, data: Any, **_: Any) -> Any:
    """Mask áp dụng cho MỌI dữ liệu trước khi rời ứng dụng đi Langfuse.

    Đây là lớp chặn cuối cho trace, song song với processor `scrub_event` của log:
    dù chỗ gọi quên scrub thì PII vẫn không lọt ra ngoài.
    """
    if isinstance(data, str):
        return scrub_text(data)
    if isinstance(data, dict):
        return {key: mask_pii(data=value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [mask_pii(data=item) for item in data]
    return data


_client_initialised = False


def configure_tracing() -> bool:
    """Khởi tạo singleton Langfuse kèm mask + environment.

    PHẢI gọi lúc app khởi động, trước request đầu tiên. Langfuse cache client theo
    public_key: nếu decorator `@observe` chạy trước và tự tạo client mặc định thì
    lần khởi tạo sau sẽ nhận lại đúng client cũ đó và `mask` không bao giờ có hiệu lực.
    Gọi sau khi biến môi trường đã nạp xong (xem "Common Mistakes" của skill langfuse).
    """
    global _client_initialised
    if _client_initialised or not LANGFUSE_SDK_AVAILABLE or Langfuse is None:
        return _client_initialised
    if not tracing_enabled():
        return False
    Langfuse(
        mask=mask_pii,
        environment=os.getenv("APP_ENV", "dev"),
    )
    _client_initialised = True
    return True


def masking_active() -> bool:
    """Client đang thực sự dùng mask của ta hay không (dùng cho health check/test)."""
    if not LANGFUSE_SDK_AVAILABLE:
        return False
    return getattr(get_client(), "_mask", None) is mask_pii


def get_langfuse_client():
    configure_tracing()
    return get_client()


def tracing_enabled() -> bool:
    return LANGFUSE_SDK_AVAILABLE and bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )


@contextmanager
def observation_span(client: Any, *, name: str, **kwargs: Any) -> Iterator[Any]:
    """Tạo span con, tự bỏ qua nếu client không hỗ trợ (dummy/fake client trong test)."""
    start = getattr(client, "start_as_current_span", None)
    if start is None:
        yield None
        return
    with start(name=name, **kwargs) as span:
        yield span


@contextmanager
def observation_generation(client: Any, *, name: str, **kwargs: Any) -> Iterator[Any]:
    """Tạo generation con. Trong block này `update_current_generation` trỏ đúng vào nó."""
    start = getattr(client, "start_as_current_generation", None)
    if start is None:
        yield None
        return
    with start(name=name, **kwargs) as generation:
        yield generation


def score_current_trace(client: Any, *, name: str, value: float, comment: str | None = None) -> None:
    scorer = getattr(client, "score_current_trace", None)
    if scorer is None:
        return
    scorer(name=name, value=value, data_type="NUMERIC", comment=comment)


def flush() -> None:
    """Đẩy nốt span còn trong buffer. Bắt buộc gọi trước khi tiến trình thoát."""
    if not LANGFUSE_SDK_AVAILABLE:
        return
    flusher = getattr(get_client(), "flush", None)
    if flusher is not None:
        flusher()
