"""Kiểm tra cấu trúc trace thật sự được sinh ra, bằng cách bắt span ở tầng OpenTelemetry.

Không cần key Langfuse hợp lệ: ta gắn InMemorySpanExporter vào client nên đọc được
đúng những span/attribute mà SDK sẽ gửi đi.
"""

from __future__ import annotations

import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app import tracing

PII_MESSAGE = (
    "What is the refund policy? Email student@vinuni.edu.vn "
    "phone 0987654321 card 4111 1111 1111 1111"
)


@pytest.fixture(scope="module")
def captured_spans():
    """Chạy agent với exporter in-memory, trả về hàm lấy cây span.

    Module-scope là bắt buộc: Langfuse cache client theo public_key, nên nếu tạo
    client mới mỗi test thì span vẫn chảy về exporter của client đầu tiên.
    """
    import os

    from langfuse import Langfuse

    previous_env = {
        key: os.environ.get(key)
        for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "APP_ENV")
    }
    os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-test-structure"
    os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-test-structure"
    os.environ["APP_ENV"] = "test"

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    client = Langfuse(
        public_key="pk-lf-test-structure",
        secret_key="sk-lf-test-structure",
        mask=tracing.mask_pii,
        environment="test",
        tracer_provider=provider,
    )
    previously_initialised = tracing._client_initialised
    tracing._client_initialised = True

    def run(message: str = PII_MESSAGE, *, expect_error: bool = False):
        from app.agent import LabAgent

        exporter.clear()
        try:
            LabAgent().run(
                user_id="u_test",
                feature="qa",
                session_id="s_test",
                message=message,
                correlation_id="req-test01",
            )
        except Exception:
            if not expect_error:
                raise
        finally:
            client.flush()
        return list(exporter.get_finished_spans())

    yield run

    tracing._client_initialised = previously_initialised
    for key, value in previous_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _by_name(spans):
    return {s.name: s for s in spans}


def test_trace_is_nested_not_flat(captured_spans) -> None:
    spans = captured_spans()
    names = _by_name(spans)

    assert {"chat-response", "retrieve-context", "resolve-prompt", "llm-generate"} <= names.keys()

    root = names["chat-response"]
    assert root.parent is None
    # Ba bước con phải nằm DƯỚI root, nếu phẳng thì không định vị được bước nào chậm.
    for child in ("retrieve-context", "resolve-prompt", "llm-generate"):
        assert names[child].parent is not None
        assert names[child].parent.span_id == root.context.span_id


def test_llm_call_is_typed_as_generation_with_model_and_usage(captured_spans) -> None:
    gen = _by_name(captured_spans())["llm-generate"]
    attrs = dict(gen.attributes)

    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["langfuse.observation.model.name"] == "claude-sonnet-4-5"
    usage = json.loads(attrs["langfuse.observation.usage_details"])
    assert usage["prompt_tokens"] > 0 and usage["completion_tokens"] > 0
    assert json.loads(attrs["langfuse.observation.cost_details"])["total"] > 0


def test_trace_has_descriptive_name_and_explicit_io(captured_spans) -> None:
    root = _by_name(captured_spans())["chat-response"]
    attrs = dict(root.attributes)

    assert attrs["langfuse.trace.name"] == "chat-response"
    assert attrs["langfuse.trace.input"]
    assert attrs["langfuse.trace.output"]
    assert attrs["langfuse.trace.tags"] == ("lab", "qa", "claude-sonnet-4-5")


def test_correlation_id_links_trace_to_logs(captured_spans) -> None:
    root = _by_name(captured_spans())["chat-response"]
    assert dict(root.attributes)["langfuse.trace.metadata.correlation_id"] == "req-test01"


def test_prompt_metadata_survives_both_trace_updates(captured_spans) -> None:
    """Hai lần update_current_trace phải merge, không được ghi đè nhau."""
    attrs = dict(_by_name(captured_spans())["chat-response"].attributes)
    assert attrs["langfuse.trace.metadata.correlation_id"] == "req-test01"
    assert attrs["langfuse.trace.metadata.prompt_name"] == "day13-chat"


def test_no_pii_in_any_span_attribute(captured_spans) -> None:
    spans = captured_spans()
    raw = json.dumps([dict(s.attributes) for s in spans], default=str)

    for secret in ("student@vinuni.edu.vn", "0987654321", "4111 1111 1111 1111", "u_test"):
        assert secret not in raw, f"PII bi ro ra trace: {secret}"
    assert "[REDACTED_EMAIL]" in raw


def test_slow_retrieval_is_isolated_to_its_own_span(captured_spans) -> None:
    """Sự cố rag_slow phải hiện ra ở đúng span retrieve-context."""
    from app.incidents import STATE

    STATE["rag_slow"] = True
    try:
        names = _by_name(captured_spans())
    finally:
        STATE["rag_slow"] = False

    retrieval_ms = (names["retrieve-context"].end_time - names["retrieve-context"].start_time) / 1e6
    llm_ms = (names["llm-generate"].end_time - names["llm-generate"].start_time) / 1e6
    assert retrieval_ms > 2000
    assert retrieval_ms > llm_ms


def test_startup_configures_masking_before_first_request() -> None:
    """Bẫy thứ tự: nếu @observe chạy trước configure_tracing thì mask không bao giờ áp dụng.

    Langfuse cache client theo public_key, nên client tạo sớm (thiếu mask) sẽ được
    dùng lại mãi. Chạy trong subprocess để có singleton sạch.
    """
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import os
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-order-check"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-order-check"
        from app.main import app
        from fastapi.testclient import TestClient
        from app.tracing import masking_active
        with TestClient(app) as client:      # kích hoạt startup event
            client.post("/chat", json={
                "user_id": "u", "session_id": "s", "feature": "qa",
                "message": "mail leak@test.vn",
            })
        print("MASKING_ACTIVE=" + str(masking_active()))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "MASKING_ACTIVE=True" in result.stdout, result.stdout + result.stderr


def test_tool_failure_marks_span_as_error(captured_spans) -> None:
    """Lỗi retrieval phải hiện level=ERROR kèm nguyên nhân, không im lặng."""
    from app.incidents import STATE

    STATE["tool_fail"] = True
    try:
        names = _by_name(captured_spans(expect_error=True))
    finally:
        STATE["tool_fail"] = False

    failed = dict(names["retrieve-context"].attributes)
    assert failed["langfuse.observation.level"] == "ERROR"
    assert "Vector store timeout" in failed["langfuse.observation.status_message"]
    # Không có generation vì pipeline dừng trước khi gọi LLM.
    assert "llm-generate" not in names
