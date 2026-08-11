from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard import build_dashboard_snapshot
from app.main import app


def _write_record(path: Path, timestamp: datetime, **record) -> None:
    payload = {"ts": timestamp.isoformat(), **record}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload) + "\n")


def test_dashboard_snapshot_aggregates_six_panels(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, 5, 0, tzinfo=timezone.utc)
    log_path = tmp_path / "logs.jsonl"
    _write_record(log_path, now - timedelta(minutes=2), event="request_received")
    _write_record(log_path, now - timedelta(minutes=1), event="request_received")
    _write_record(log_path, now - timedelta(minutes=1), event="request_failed", error_type="TimeoutError")
    _write_record(
        log_path,
        now - timedelta(seconds=30),
        event="response_sent",
        latency_ms=250,
        cost_usd=0.01,
        tokens_in=20,
        tokens_out=40,
        quality_score=0.8,
    )

    snapshot = build_dashboard_snapshot(log_path=log_path, now=now)
    panels = {panel["id"]: panel for panel in snapshot["panels"]}

    assert set(panels) == {"latency", "traffic", "errors", "cost", "tokens", "quality"}
    assert panels["latency"]["values"]["p95"] == 250
    assert panels["traffic"]["values"]["count"] == 2
    assert panels["errors"]["values"]["error_rate_pct"] == 50
    assert panels["cost"]["values"]["total"] == 0.01
    assert panels["tokens"]["values"] == {"tokens_in": 20, "tokens_out": 40}
    assert panels["quality"]["values"]["mean"] == 0.8


def test_dashboard_page_exposes_runtime_contract() -> None:
    with TestClient(app) as client:
        page = client.get("/dashboard")

    assert page.status_code == 200
    assert "Day 13 AI Observability" in page.text
    assert "Time range: <b>60 minutes</b>" in page.text
    assert "setInterval(refresh, 30000)" in page.text
