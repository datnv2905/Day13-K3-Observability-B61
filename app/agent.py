from __future__ import annotations

import time
from dataclasses import dataclass

from . import metrics
from .mock_llm import FakeLLM
from .mock_rag import retrieve
from .pii import hash_user_id, summarize_text
from .prompt_management import resolve_prompt
from .tracing import (
    get_langfuse_client,
    observation_generation,
    observation_span,
    observe,
    score_current_trace,
    tracing_enabled,
)


@dataclass
class AgentResult:
    answer: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    quality_score: float


class LabAgent:
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model
        self.llm = FakeLLM(model=model)

    # capture_input/output=False: nếu bật, Langfuse sẽ nuốt trọn mọi tham số của hàm
    # (gồm cả user_id thô). Input/output được set thủ công bên dưới, đã qua scrub.
    @observe(name="chat-response", capture_input=False, capture_output=False)
    def run(
        self,
        user_id: str,
        feature: str,
        session_id: str,
        message: str,
        correlation_id: str | None = None,
    ) -> AgentResult:
        started = time.perf_counter()
        langfuse_client = get_langfuse_client()

        docs = self._retrieve_context(langfuse_client, message)
        prompt = self._resolve_prompt(langfuse_client, feature=feature, docs=docs, message=message)

        with observation_generation(
            langfuse_client,
            name="llm-generate",
            input=summarize_text(prompt.text, max_len=500),
            model=self.model,
        ):
            response = self.llm.generate(prompt.text)
            cost_usd = self._estimate_cost(
                response.usage.input_tokens, response.usage.output_tokens
            )
            langfuse_client.update_current_generation(
                output=summarize_text(response.text, max_len=500),
                model=self.model,
                metadata={
                    "doc_count": len(docs),
                    "query_preview": summarize_text(message),
                    "prompt_name": prompt.name,
                    "prompt_label": prompt.label,
                    "prompt_version": prompt.version,
                    "prompt_source": prompt.source,
                    "prompt_fetch_error": prompt.fetch_error,
                },
                usage_details={
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                },
                cost_details={"total": cost_usd},
                prompt=prompt.managed_prompt,
            )

        quality_score = self._heuristic_quality(message, response.text, docs)
        latency_ms = int((time.perf_counter() - started) * 1000)

        # Hai lần update_current_trace là cố ý: lần này mang context của request,
        # lần cuối chỉ mang prompt metadata để giữ đúng contract của public test.
        # Metadata được Langfuse flatten theo từng key nên hai lần gọi sẽ merge.
        langfuse_client.update_current_trace(
            name="chat-response",
            input=summarize_text(message, max_len=500),
            output=summarize_text(response.text, max_len=500),
            user_id=hash_user_id(user_id),
            session_id=session_id,
            tags=["lab", feature, self.model],
            metadata={
                # Cầu nối Logs <-> Traces: dán correlation_id của log vào trace.
                "correlation_id": correlation_id,
                "doc_count": len(docs),
                "latency_ms": latency_ms,
            },
        )
        # quality_score là score thật trên Langfuse, không chỉ là metadata,
        # nên lọc/vẽ biểu đồ theo chất lượng được trong UI.
        score_current_trace(
            langfuse_client,
            name="quality_proxy",
            value=quality_score,
            comment=f"heuristic quality proxy, docs={len(docs)}",
        )
        langfuse_client.update_current_trace(
            user_id=hash_user_id(user_id),
            session_id=session_id,
            tags=["lab", feature, self.model],
            metadata={
                "prompt_name": prompt.name,
                "prompt_label": prompt.label,
                "prompt_version": prompt.version,
                "prompt_source": prompt.source,
            },
        )

        metrics.record_request(
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            quality_score=quality_score,
        )

        return AgentResult(
            answer=response.text,
            latency_ms=latency_ms,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            cost_usd=cost_usd,
            quality_score=quality_score,
        )

    def _retrieve_context(self, langfuse_client, message: str) -> list[str]:
        """Span riêng cho RAG — nếu không tách, sự cố rag_slow sẽ vô hình trong trace."""
        with observation_span(
            langfuse_client,
            name="retrieve-context",
            input=summarize_text(message),
            metadata={"observation_type": "retriever"},
        ) as span:
            try:
                docs = retrieve(message)
            except Exception as exc:
                if span is not None:
                    span.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")
                raise
            if span is not None:
                span.update(output={"doc_count": len(docs), "docs": docs})
            return docs

    def _resolve_prompt(self, langfuse_client, *, feature: str, docs: list[str], message: str):
        with observation_span(
            langfuse_client,
            name="resolve-prompt",
            metadata={"observation_type": "prompt-management"},
        ) as span:
            prompt = resolve_prompt(
                langfuse_client,
                feature=feature,
                docs=docs,
                message=message,
                enabled=tracing_enabled(),
            )
            if span is not None:
                span.update(
                    output={
                        "prompt_name": prompt.name,
                        "prompt_label": prompt.label,
                        "prompt_version": prompt.version,
                        "prompt_source": prompt.source,
                    },
                    # Fallback nghĩa là prompt lấy từ Langfuse thất bại -> cảnh báo trên trace.
                    level="WARNING" if prompt.source != "langfuse" else None,
                    status_message=prompt.fetch_error,
                )
            return prompt

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        input_cost = (tokens_in / 1_000_000) * 3
        output_cost = (tokens_out / 1_000_000) * 15
        return round(input_cost + output_cost, 6)

    def _heuristic_quality(self, question: str, answer: str, docs: list[str]) -> float:
        score = 0.5
        if docs:
            score += 0.2
        if len(answer) > 40:
            score += 0.1
        if question.lower().split()[0:1] and any(token in answer.lower() for token in question.lower().split()[:3]):
            score += 0.1
        if "[REDACTED" in answer:
            score -= 0.2
        return round(max(0.0, min(1.0, score)), 2)
