from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import logging_config
from app.main import app


def test_chat_response_log_exposes_quality_for_dashboard(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            headers={"x-request-id": "req-phase1-test"},
            json={
                "user_id": "student-01",
                "session_id": "session-01",
                "feature": "qa",
                "message": "Explain observability to student@vinuni.edu.vn",
            },
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-phase1-test"
    assert float(response.headers["x-response-time-ms"]) >= 0
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    api_events = [event for event in events if event["service"] == "api"]
    assert api_events
    assert all(event["correlation_id"] == "req-phase1-test" for event in api_events)
    assert all(
        {"user_id_hash", "session_id", "feature", "model", "env"}.issubset(event)
        for event in api_events
    )
    assert "student@vinuni.edu.vn" not in json.dumps(events)
    response_event = next(event for event in events if event["event"] == "response_sent")
    assert response_event["quality_score"] == response.json()["quality_score"]
