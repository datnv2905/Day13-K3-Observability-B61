from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from .logging_config import LOG_PATH


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "dashboard.yaml"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((percentile / 100) * len(ordered) + 0.5) - 1))
    return round(float(ordered[index]), 2)


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _threshold_status(value: float, operator: str, target: float) -> str:
    passed = value <= target if operator == "lte" else value >= target
    return "healthy" if passed else "breached"


def build_dashboard_snapshot(
    *,
    log_path: Path | None = None,
    config_path: Path = CONFIG_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))["dashboard"]
    window_minutes = int(config["time_range_minutes"])
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_start = current_time - timedelta(minutes=window_minutes)

    records = []
    for record in _load_records(log_path or LOG_PATH):
        timestamp = _parse_timestamp(record.get("ts"))
        if timestamp is not None and window_start <= timestamp <= current_time:
            records.append((timestamp, record))

    request_records = [item for item in records if item[1].get("event") == "request_received"]
    failure_records = [item for item in records if item[1].get("event") == "request_failed"]
    response_records = [item for item in records if item[1].get("event") == "response_sent"]

    latencies = [float(record.get("latency_ms", 0)) for _, record in response_records]
    costs = [float(record.get("cost_usd", 0)) for _, record in response_records]
    qualities = [float(record.get("quality_score", 0)) for _, record in response_records]
    tokens_in = sum(int(record.get("tokens_in", 0)) for _, record in response_records)
    tokens_out = sum(int(record.get("tokens_out", 0)) for _, record in response_records)

    active_minutes = 1.0
    if len(request_records) > 1:
        active_minutes = max(
            1.0,
            (max(ts for ts, _ in request_records) - min(ts for ts, _ in request_records)).total_seconds()
            / 60,
        )
    traffic_rate = round(len(request_records) / active_minutes, 2)
    error_rate = round((len(failure_records) / len(request_records)) * 100, 2) if request_records else 0.0
    error_breakdown: dict[str, int] = defaultdict(int)
    for _, record in failure_records:
        error_breakdown[str(record.get("error_type") or "unknown")] += 1

    by_minute: dict[str, dict[str, float]] = defaultdict(
        lambda: {"requests": 0, "cost_usd": 0.0, "latency_ms": 0.0, "responses": 0}
    )
    for timestamp, record in records:
        bucket = timestamp.strftime("%H:%M")
        if record.get("event") == "request_received":
            by_minute[bucket]["requests"] += 1
        if record.get("event") == "response_sent":
            by_minute[bucket]["cost_usd"] += float(record.get("cost_usd", 0))
            by_minute[bucket]["latency_ms"] += float(record.get("latency_ms", 0))
            by_minute[bucket]["responses"] += 1

    series = []
    for minute, values in sorted(by_minute.items()):
        responses = values["responses"]
        series.append(
            {
                "minute": minute,
                "requests": int(values["requests"]),
                "cost_usd": round(values["cost_usd"], 6),
                "latency_avg_ms": round(values["latency_ms"] / responses, 2) if responses else 0.0,
            }
        )

    raw_values = {
        "latency": {
            "primary": _percentile(latencies, 95),
            "values": {
                "p50": _percentile(latencies, 50),
                "p95": _percentile(latencies, 95),
                "p99": _percentile(latencies, 99),
            },
        },
        "traffic": {
            "primary": traffic_rate,
            "values": {"count": len(request_records), "rate_per_minute": traffic_rate},
        },
        "errors": {
            "primary": error_rate,
            "values": {
                "error_rate_pct": error_rate,
                "total_errors": len(failure_records),
                "breakdown": dict(error_breakdown),
            },
        },
        "cost": {
            "primary": round(sum(costs), 6),
            "values": {"total": round(sum(costs), 6)},
        },
        "tokens": {
            "primary": tokens_in + tokens_out,
            "values": {"tokens_in": tokens_in, "tokens_out": tokens_out},
        },
        "quality": {
            "primary": round(sum(qualities) / len(qualities), 3) if qualities else 0.0,
            "values": {
                "mean": round(sum(qualities) / len(qualities), 3) if qualities else 0.0
            },
        },
    }

    panels = []
    for panel_config in config["panels"]:
        panel_id = panel_config["id"]
        threshold = panel_config["threshold"]
        values = raw_values[panel_id]
        panels.append(
            {
                "id": panel_id,
                "title": panel_config["title"],
                "unit": panel_config["unit"],
                "threshold": threshold,
                "status": _threshold_status(
                    float(values["primary"]),
                    threshold["operator"],
                    float(threshold["value"]),
                ),
                **values,
            }
        )

    return {
        "title": config["title"],
        "source": "data/logs.jsonl",
        "generated_at": current_time.isoformat(),
        "time_range_minutes": window_minutes,
        "refresh_seconds": int(config["refresh_seconds"]),
        "record_count": len(records),
        "panels": panels,
        "series": series,
    }


def dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Day 13 AI Observability</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, Segoe UI, sans-serif; }
    body { margin: 0; background: #07111f; color: #e5eefb; }
    header { padding: 24px 32px 12px; display: flex; justify-content: space-between; gap: 20px; align-items: end; }
    h1 { margin: 0 0 6px; font-size: 25px; }
    .muted { color: #8da4c2; font-size: 13px; }
    .status { display: flex; gap: 10px; flex-wrap: wrap; justify-content: end; }
    .pill { border: 1px solid #27405e; border-radius: 999px; padding: 7px 11px; background: #0d1c2f; font-size: 12px; }
    main { padding: 16px 32px 32px; display: grid; grid-template-columns: repeat(3, minmax(240px, 1fr)); gap: 16px; }
    .panel { border: 1px solid #213854; border-radius: 14px; background: linear-gradient(145deg, #0d1d31, #0a1728); padding: 18px; min-height: 210px; box-shadow: 0 8px 30px #0004; }
    .panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .panel h2 { margin: 0; font-size: 16px; }
    .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; margin-right: 6px; }
    .healthy .dot { background: #42d392; box-shadow: 0 0 10px #42d39288; }
    .breached .dot { background: #ff6b6b; box-shadow: 0 0 10px #ff6b6b88; }
    .metric { font-size: 35px; font-weight: 750; margin: 24px 0 4px; letter-spacing: -1px; }
    .unit { color: #8da4c2; font-size: 12px; }
    .details { margin-top: 18px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .detail { background: #091524; border-radius: 8px; padding: 9px; font-size: 12px; overflow-wrap: anywhere; }
    .detail b { display: block; color: #8da4c2; font-size: 10px; text-transform: uppercase; margin-bottom: 4px; }
    .threshold { margin-top: 14px; border-top: 1px solid #1d3149; padding-top: 11px; color: #a9bad0; font-size: 12px; }
    .bars { height: 34px; display: flex; align-items: end; gap: 3px; margin-top: 13px; }
    .bar { flex: 1; min-width: 3px; background: #54a7ff; border-radius: 3px 3px 0 0; opacity: .72; }
    .empty { color: #8da4c2; margin-top: 28px; }
    @media (max-width: 1000px) { main { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 650px) { main { grid-template-columns: 1fr; padding: 12px; } header { padding: 18px 14px 8px; align-items: start; flex-direction: column; } }
  </style>
</head>
<body>
  <header>
    <div><h1>Day 13 AI Observability</h1><div class="muted">Runtime source: data/logs.jsonl</div></div>
    <div class="status">
      <span class="pill">Time range: <b>60 minutes</b></span>
      <span class="pill">Refresh: <b>30 seconds</b></span>
      <span class="pill" id="updated">Loading…</span>
    </div>
  </header>
  <main id="panels"></main>
  <script>
    const labels = {
      latency: v => [`P50 ${v.p50} ms`, `P95 ${v.p95} ms`, `P99 ${v.p99} ms`],
      traffic: v => [`Count ${v.count}`, `Rate ${v.rate_per_minute}/min`],
      errors: v => [`Errors ${v.total_errors}`, `Rate ${v.error_rate_pct}%`, `Types ${JSON.stringify(v.breakdown)}`],
      cost: v => [`Total $${v.total}`],
      tokens: v => [`Input ${v.tokens_in}`, `Output ${v.tokens_out}`],
      quality: v => [`Mean ${v.mean}`]
    };
    const primary = {
      latency: p => `${p.primary}`,
      traffic: p => `${p.primary}`,
      errors: p => `${p.primary}`,
      cost: p => `$${p.primary}`,
      tokens: p => `${p.primary}`,
      quality: p => `${p.primary}`
    };
    function bars(series, id) {
      const key = id === 'cost' ? 'cost_usd' : id === 'latency' ? 'latency_avg_ms' : 'requests';
      const values = series.map(point => Number(point[key] || 0));
      if (!values.length) return '<div class="empty">No data in current window</div>';
      const max = Math.max(...values, 1);
      return `<div class="bars">${values.map(value => `<i class="bar" style="height:${Math.max(8, value / max * 34)}px" title="${value}"></i>`).join('')}</div>`;
    }
    async function refresh() {
      const response = await fetch('/dashboard/data', {cache: 'no-store'});
      const data = await response.json();
      document.getElementById('updated').innerHTML = `Updated: <b>${new Date(data.generated_at).toLocaleTimeString()}</b>`;
      document.getElementById('panels').innerHTML = data.panels.map(panel => {
        const target = `${panel.threshold.aggregation} ${panel.threshold.operator === 'lte' ? '≤' : '≥'} ${panel.threshold.value}`;
        return `<section class="panel ${panel.status}">
          <div class="panel-head"><h2>${panel.title}</h2><span class="muted"><i class="dot"></i>${panel.status}</span></div>
          <div class="metric">${primary[panel.id](panel)}</div><div class="unit">${panel.unit}</div>
          ${bars(data.series, panel.id)}
          <div class="details">${labels[panel.id](panel.values).map((text, index) => `<div class="detail"><b>Value ${index + 1}</b>${text}</div>`).join('')}</div>
          <div class="threshold">SLO threshold: ${target}</div>
        </section>`;
      }).join('');
    }
    refresh().catch(error => document.getElementById('panels').innerHTML = `<p>${error}</p>`);
    setInterval(refresh, 30000);
  </script>
</body>
</html>"""
