"""SLI latency phải đo thời gian người dùng chờ, không phải thời gian agent chạy.

Bug từng gặp: latency_ms bấm giờ bên trong agent.run() nên bỏ qua thời gian request
nằm chờ. Dưới tải, người dùng chờ 13 giây mà log vẫn ghi 2.6 giây, khiến alert
`high_latency_p95 > 3000ms` không bao giờ kêu được.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app import logging_config
from app.main import app

BLOCK_SECONDS = 0.3
CONCURRENT_REQUESTS = 3

PAYLOAD = {
    "user_id": "student-01",
    "session_id": "session-01",
    "feature": "qa",
    "message": "Explain observability",
}


def _post(client: TestClient) -> dict:
    response = client.post("/chat", json=PAYLOAD)
    assert response.status_code == 200
    return response.json()


def test_queue_wait_shows_up_in_latency_ms(monkeypatch) -> None:
    """Đây là test bắt đúng con bug: khi request xếp hàng, latency_ms phải phản
    ánh thời gian chờ, còn agent_latency_ms thì không.

    Lúc rảnh hai con số chỉ chênh vài ms nên so sánh chúng chẳng chứng minh được gì.
    Phải tạo hàng đợi thật mới phân biệt được đo đúng chỗ hay đo sai chỗ.
    """

    def blocking_retrieve(message: str) -> list[str]:
        time.sleep(BLOCK_SECONDS)
        return ["doc"]

    monkeypatch.setattr("app.agent.retrieve", blocking_retrieve)

    bodies: list[dict] = []
    lock = threading.Lock()

    with TestClient(app) as client:

        def send() -> None:
            body = client.post("/chat", json=PAYLOAD).json()
            with lock:
                bodies.append(body)

        threads = [threading.Thread(target=send) for _ in range(CONCURRENT_REQUESTS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert len(bodies) == CONCURRENT_REQUESTS
    worst = max(bodies, key=lambda body: body["latency_ms"])
    queue_wait_ms = worst["latency_ms"] - worst["agent_latency_ms"]

    # Request cuối trong hàng phải chờ ít nhất một lượt xử lý trước nó.
    assert queue_wait_ms > BLOCK_SECONDS * 1000 * 0.8, (
        f"latency_ms={worst['latency_ms']} agent_latency_ms={worst['agent_latency_ms']}: "
        "latency_ms không thấy thời gian xếp hàng, tức là đang bấm giờ bên trong agent"
    )


def test_response_sent_log_carries_the_user_facing_latency(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        body = _post(client)

    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    response_event = next(event for event in events if event["event"] == "response_sent")

    # Dashboard, SLO và alert đều đọc latency_ms từ log này, nên nó phải khớp
    # đúng con số trả về cho người dùng.
    assert response_event["latency_ms"] == body["latency_ms"]
    assert response_event["agent_latency_ms"] == body["agent_latency_ms"]


def test_metrics_snapshot_uses_the_same_latency_as_the_log(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        body = _post(client)
        snapshot = client.get("/metrics").json()

    # /metrics và log phải đo cùng một thứ, nếu không dashboard và API sẽ nói
    # hai con số khác nhau cho cùng một sự cố.
    assert snapshot["latency_p99"] >= body["latency_ms"] * 0.9
