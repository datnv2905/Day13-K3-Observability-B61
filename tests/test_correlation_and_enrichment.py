from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import logging_config
from app.logging_config import configure_logging, get_logger
from app.main import app

CORRELATION_ID_PATTERN = re.compile(r"^req-[0-9a-f]{8}$")
ENRICHMENT_FIELDS = {"user_id_hash", "session_id", "feature", "model", "env"}


def _read_events(log_path: Path) -> list[dict]:
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _post(client: TestClient, message: str = "Explain observability", **headers: str):
    return client.post(
        "/chat",
        json={
            "user_id": "student-01",
            "session_id": "session-01",
            "feature": "qa",
            "message": message,
        },
        headers=headers or None,
    )


def test_generated_correlation_id_is_returned_in_headers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")

    with TestClient(app) as client:
        response = _post(client)

    assert response.status_code == 200
    correlation_id = response.headers["x-request-id"]
    assert CORRELATION_ID_PATTERN.match(correlation_id)
    assert correlation_id == response.json()["correlation_id"]
    assert float(response.headers["x-response-time-ms"]) >= 0


def test_client_supplied_correlation_id_is_preserved(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        response = _post(client, **{"x-request-id": "req-from-client"})

    assert response.headers["x-request-id"] == "req-from-client"
    assert response.json()["correlation_id"] == "req-from-client"

    api_events = [e for e in _read_events(log_path) if e.get("service") == "api"]
    assert api_events
    assert all(event["correlation_id"] == "req-from-client" for event in api_events)


def test_api_logs_carry_enrichment_metadata(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        _post(client)

    api_events = [e for e in _read_events(log_path) if e.get("service") == "api"]
    assert {e["event"] for e in api_events} >= {"request_received", "response_sent"}
    for event in api_events:
        assert ENRICHMENT_FIELDS.issubset(event.keys())
        # user_id không bao giờ được ghi nguyên văn, chỉ ghi hash.
        assert event["user_id_hash"] != "student-01"


def test_contextvars_do_not_leak_between_requests(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        first = _post(client)
        second = _post(client)

    assert first.json()["correlation_id"] != second.json()["correlation_id"]

    api_events = [e for e in _read_events(log_path) if e.get("service") == "api"]
    ids = {event["correlation_id"] for event in api_events}
    assert ids == {first.json()["correlation_id"], second.json()["correlation_id"]}


def test_scrub_processor_redacts_pii_not_passed_through_summarize(monkeypatch, tmp_path: Path) -> None:
    """Lớp chặn cuối: PII thô ghi thẳng vào payload vẫn phải bị che."""
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    configure_logging()
    get_logger().info(
        "raw_probe",
        service="api",
        correlation_id="req-probe01",
        payload={"note": "mail a@b.vn phone 0912345678 card 4111111111111111"},
    )

    raw = log_path.read_text(encoding="utf-8")
    assert "a@b.vn" not in raw
    assert "0912345678" not in raw
    assert "4111111111111111" not in raw
    assert "[REDACTED_EMAIL]" in raw
    assert "[REDACTED_PHONE_VN]" in raw
    assert "[REDACTED_CREDIT_CARD]" in raw


def test_chat_request_with_pii_never_logs_raw_values(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        _post(client, message="Email student@vinuni.edu.vn phone 0987654321")

    raw = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in raw
    assert "0987654321" not in raw
