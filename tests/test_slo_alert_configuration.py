from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_yaml(relative_path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def test_slos_match_dashboard_thresholds_and_have_no_template_text() -> None:
    dashboard = load_yaml("config/dashboard.yaml")["dashboard"]
    slo = load_yaml("config/slo.yaml")
    raw_slo = (REPO_ROOT / "config/slo.yaml").read_text(encoding="utf-8")

    assert "TODO" not in raw_slo
    assert "Replace with" not in raw_slo
    assert slo["evaluation_window"] == f"{dashboard['time_range_minutes']}m"
    assert slo["refresh_seconds"] == dashboard["refresh_seconds"]

    thresholds = {panel["id"]: panel["threshold"] for panel in dashboard["panels"]}
    assert slo["slis"]["latency_p95_ms"]["objective"] == thresholds["latency"]["value"]
    assert slo["slis"]["latency_p95_ms"]["operator"] == thresholds["latency"]["operator"]
    assert slo["slis"]["error_rate_pct"]["objective"] == thresholds["errors"]["value"]
    assert slo["slis"]["error_rate_pct"]["operator"] == thresholds["errors"]["operator"]
    assert slo["slis"]["cost_total_usd"]["objective"] == thresholds["cost"]["value"]
    assert slo["slis"]["quality_score_avg"]["objective"] == thresholds["quality"]["value"]

    guardrails = slo["guardrails"]
    assert guardrails["traffic_rate_per_minute"]["objective"] == thresholds["traffic"]["value"]
    assert guardrails["tokens_in_total"]["objective"] == thresholds["tokens"]["value"]
    assert guardrails["tokens_out_total"]["objective"] == thresholds["tokens"]["value"]


def test_alerts_are_complete_symptom_based_and_link_to_runbooks() -> None:
    alerts = load_yaml("config/alert_rules.yaml")["alerts"]
    raw_alerts = (REPO_ROOT / "config/alert_rules.yaml").read_text(encoding="utf-8")
    runbooks = (REPO_ROOT / "docs/alerts.md").read_text(encoding="utf-8")

    assert len(alerts) == 4
    assert "TODO" not in raw_alerts
    assert "TODO" not in runbooks
    assert {alert["type"] for alert in alerts} == {"symptom-based"}
    assert {alert["dashboard_panel"] for alert in alerts} == {
        "latency",
        "errors",
        "quality",
        "cost",
    }
    assert {alert["sli"] for alert in alerts} == {
        "latency_p95_ms",
        "error_rate_pct",
        "quality_score_avg",
        "cost_total_usd",
    }
    assert all(alert["owner"] == "observability-oncall" for alert in alerts)
    assert all(alert["minimum_samples"] == 20 for alert in alerts)

    for index in range(1, len(alerts) + 1):
        assert f"## Alert {index}" in runbooks
    for field in (
        "- Tên:",
        "- Severity:",
        "- SLI/SLO liên quan:",
        "- Điều kiện và thời gian duy trì:",
        "- Ảnh hưởng tới người dùng:",
        "- Mitigation tạm thời:",
        "- Owner:",
    ):
        assert f"{field}\n" not in runbooks

    # "Ba bước kiểm tra" là tiêu đề của một danh sách lồng nhau, nên có thể kết
    # thúc bằng dấu hai chấm. MỖI alert phải thực sự có đủ ba tầng điều tra.
    assert runbooks.count("**Metrics:**") == len(alerts)
    assert runbooks.count("**Traces:**") == len(alerts)
    assert runbooks.count("**Logs:**") == len(alerts)
