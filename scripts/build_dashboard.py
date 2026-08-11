"""Dựng dashboard 6 panel từ data/logs.jsonl theo contract config/dashboard.yaml.

`config/dashboard.yaml` quy định panel nào, đơn vị gì, tổng hợp thế nào và threshold
bao nhiêu. Script này đọc đúng contract đó rồi render ra một file HTML tự chứa để
chụp ảnh làm evidence — không hard-code giá trị nào.

    python scripts/build_dashboard.py
    python scripts/build_dashboard.py --open        # dựng xong mở luôn trình duyệt

Percentile dùng chung hàm với /metrics (app.metrics.percentile) nên số trên dashboard
và số trên API luôn khớp nhau.
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile

DEFAULT_LOGS = REPO_ROOT / "data" / "logs.jsonl"
DEFAULT_CONFIG = REPO_ROOT / "config" / "dashboard.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "submission" / "evidence" / "dashboard.html"


# --------------------------------------------------------------------------- data


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"Không tìm thấy {path}. Chạy API rồi `python scripts/load_test.py` trước."
        )
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not records:
        raise SystemExit(f"{path} không có bản ghi JSON hợp lệ.")
    return records


def parse_ts(record: dict) -> datetime | None:
    raw = record.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def select_window(records: list[dict], minutes: int) -> tuple[list[dict], datetime, datetime]:
    """Cửa sổ tính lùi từ bản ghi mới nhất, để dashboard vẫn đọc được log cũ."""
    stamped = [(parse_ts(r), r) for r in records]
    stamped = [(ts, r) for ts, r in stamped if ts is not None]
    if not stamped:
        raise SystemExit("Không bản ghi nào có trường 'ts' hợp lệ.")
    window_end = max(ts for ts, _ in stamped)
    window_start = window_end - timedelta(minutes=minutes)
    inside = [r for ts, r in stamped if window_start <= ts <= window_end]
    return inside, window_start, window_end


def minute_key(record: dict) -> str:
    ts = parse_ts(record)
    return ts.strftime("%H:%M") if ts else "??:??"


def bucket_by_minute(
    records: list[dict], value_of, start: datetime, end: datetime
) -> list[tuple[str, float]]:
    """Trục thời gian phải liên tục: phút không có traffic vẫn là một cột 0."""
    buckets: dict[str, float] = defaultdict(float)
    cursor = start.replace(second=0, microsecond=0)
    last = end.replace(second=0, microsecond=0)
    while cursor <= last:
        buckets[cursor.strftime("%H:%M")] = 0.0
        cursor += timedelta(minutes=1)
    for record in records:
        buckets[minute_key(record)] += value_of(record)
    return sorted(buckets.items())


# ----------------------------------------------------------------------- compute


def compute_panels(
    records: list[dict], window_minutes: int, start: datetime, end: datetime
) -> dict[str, dict]:
    received = [r for r in records if r.get("event") == "request_received"]
    sent = [r for r in records if r.get("event") == "response_sent"]
    failed = [r for r in records if r.get("event") == "request_failed"]

    latencies = [r["latency_ms"] for r in sent if isinstance(r.get("latency_ms"), int)]
    costs = [r for r in sent if isinstance(r.get("cost_usd"), (int, float))]
    qualities = [r["quality_score"] for r in sent if isinstance(r.get("quality_score"), (int, float))]

    traffic_buckets = bucket_by_minute(received, lambda _: 1, start, end)
    # rate tính trên số phút thực sự có traffic, không chia đều cả cửa sổ rỗng.
    active_minutes = max(1, sum(1 for _, count in traffic_buckets if count))
    error_rate = (len(failed) / len(received) * 100) if received else 0.0

    return {
        "latency": {
            "values": {
                "p50": percentile(latencies, 50),
                "p95": percentile(latencies, 95),
                "p99": percentile(latencies, 99),
            },
            "sample_size": len(latencies),
        },
        "traffic": {
            "buckets": traffic_buckets,
            "count": len(received),
            "rate_per_minute": round(len(received) / active_minutes, 2),
        },
        "errors": {
            "error_rate_pct": round(error_rate, 2),
            "failed": len(failed),
            "received": len(received),
            "breakdown": Counter(r.get("error_type", "unknown") for r in failed),
        },
        "cost": {
            "buckets": bucket_by_minute(costs, lambda r: float(r["cost_usd"]), start, end),
            "total": round(sum(float(r["cost_usd"]) for r in costs), 6),
        },
        "tokens": {
            "tokens_in": sum(r.get("tokens_in", 0) for r in sent),
            "tokens_out": sum(r.get("tokens_out", 0) for r in sent),
        },
        "quality": {
            "mean": round(sum(qualities) / len(qualities), 4) if qualities else 0.0,
            "sample_size": len(qualities),
        },
        "_meta": {"window_minutes": window_minutes, "responses": len(sent)},
    }


def threshold_state(observed: float, operator: str, limit: float) -> tuple[bool, str]:
    ok = observed <= limit if operator == "lte" else observed >= limit
    return ok, ("đạt" if ok else "vi phạm")


# ------------------------------------------------------------------------ render

# Palette: slot 1 blue + slot 2 orange, đã chạy scripts/validate_palette.js
# (light ΔE 24.7 / dark ΔE 26.8, ngưỡng CVD >= 8) — PASS cả hai chế độ.
CSS = """
:root {
  color-scheme: light;
  --surface-1: #fcfcfb; --page: #f9f9f7;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --muted: #898781;
  --grid: #e1e0d9; --baseline: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --track: #cde2fb;
  --good: #0ca30c; --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface-1: #1a1a19; --page: #0d0d0d;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --track: #0d366b;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1: #1a1a19; --page: #0d0d0d;
  --text-primary: #ffffff; --text-secondary: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --track: #0d366b;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px; background: var(--page); color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; font-size: 14px;
}
header { max-width: 1180px; margin: 0 auto 20px; }
h1 { font-size: 20px; font-weight: 600; margin: 0 0 6px; }
.meta { color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.meta code { color: var(--text-primary); }
.grid {
  max-width: 1180px; margin: 0 auto;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px;
}
.panel {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 10px; padding: 16px 18px 14px; min-width: 0;
}
.panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.panel-title { font-size: 14px; font-weight: 600; margin: 0; }
.panel-unit { color: var(--muted); font-size: 12px; white-space: nowrap; }
.panel-sub { color: var(--text-secondary); font-size: 12px; margin: 4px 0 12px; }
.hero { font-size: 30px; font-weight: 600; line-height: 1.1; margin: 2px 0 0; }
.hero-note { color: var(--text-secondary); font-size: 12px; margin: 4px 0 10px; }
.chip {
  display: inline-flex; align-items: center; gap: 5px; font-size: 12px;
  padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border);
  color: var(--text-secondary); white-space: nowrap;
}
.chip-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.legend { display: flex; gap: 14px; flex-wrap: wrap; margin: 0 0 8px; }
.legend-item { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 12px; }
.legend-key { width: 10px; height: 10px; border-radius: 2px; flex: none; }
svg { display: block; width: 100%; height: auto; overflow: visible; }
.axis-text { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.value-text { fill: var(--text-primary); font-size: 12px; font-weight: 600; }
.grid-line { stroke: var(--grid); stroke-width: 1; }
.baseline { stroke: var(--baseline); stroke-width: 1; }
.threshold-line { stroke: var(--critical); stroke-width: 1; }
.threshold-text { fill: var(--text-secondary); font-size: 11px; }
.bar { cursor: default; }
.bar:hover { opacity: 0.82; }
details { margin-top: 12px; }
summary { color: var(--text-secondary); font-size: 12px; cursor: pointer; }
table { border-collapse: collapse; margin-top: 8px; width: 100%; font-size: 12px; }
th, td { text-align: left; padding: 4px 8px 4px 0; border-bottom: 1px solid var(--grid); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.empty { color: var(--text-secondary); font-size: 12px; padding: 10px 0 4px; }
#tip {
  position: fixed; pointer-events: none; opacity: 0; transition: opacity .1s;
  background: var(--surface-1); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 9px;
  font-size: 12px; box-shadow: 0 2px 10px rgba(0,0,0,.15); z-index: 10;
}
footer { max-width: 1180px; margin: 20px auto 0; color: var(--muted); font-size: 12px; }
"""

TOOLTIP_JS = """
const tip = document.getElementById('tip');
for (const mark of document.querySelectorAll('[data-tip]')) {
  mark.addEventListener('pointerenter', e => {
    tip.textContent = e.currentTarget.dataset.tip; tip.style.opacity = '1';
  });
  mark.addEventListener('pointermove', e => {
    tip.style.left = (e.clientX + 14) + 'px';
    tip.style.top = (e.clientY + 14) + 'px';
  });
  mark.addEventListener('pointerleave', () => { tip.style.opacity = '0'; });
}
"""


def esc(text: object) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# Hệ toạ độ SVG xấp xỉ bề rộng panel thật (~340–560px) nên 1 user unit ≈ 1px và
# chữ trong SVG giữ đúng cỡ. Dùng viewBox rộng 1000 sẽ co chữ xuống ~34%.
VIEW_W = 400


def compact(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}"


def bar_path(x: float, y: float, width: float, height: float, radius: float = 4) -> str:
    """Bar ngang: đầu dữ liệu bo 4px, chân bám baseline vuông góc."""
    r = min(radius, max(0.0, width))
    if r <= 0:
        return f"M{x},{y} h{width} v{height} h{-width} Z"
    return (
        f"M{x},{y} H{x + width - r} Q{x + width},{y} {x + width},{y + r} "
        f"V{y + height - r} Q{x + width},{y + height} {x + width - r},{y + height} "
        f"H{x} Z"
    )


def column_path(x: float, y_top: float, width: float, y_base: float, radius: float = 4) -> str:
    """Cột dọc: nắp bo 4px, chân vuông bám baseline."""
    height = y_base - y_top
    r = min(radius, max(0.0, height), width / 2)
    if r <= 0:
        return f"M{x},{y_base} h{width} Z"
    return (
        f"M{x},{y_base} V{y_top + r} Q{x},{y_top} {x + r},{y_top} "
        f"H{x + width - r} Q{x + width},{y_top} {x + width},{y_top + r} "
        f"V{y_base} Z"
    )


def status_chip(ok: bool, label: str) -> str:
    color = "var(--good)" if ok else "var(--critical)"
    icon = "✓" if ok else "✗"
    return (
        f'<span class="chip"><span class="chip-dot" style="background:{color}"></span>'
        f"{icon} {esc(label)}</span>"
    )


def table_view(headers: list[str], rows: list[list[str]], caption: str = "Bảng dữ liệu") -> str:
    head = "".join(
        f'<th class="num">{esc(h)}</th>' if i else f"<th>{esc(h)}</th>"
        for i, h in enumerate(headers)
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="num">{esc(c)}</td>' if i else f"<td>{esc(c)}</td>"
            for i, c in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return (
        f"<details><summary>{esc(caption)}</summary>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></details>"
    )


def horizontal_bars(
    items: list[tuple[str, float]],
    unit: str,
    threshold: float | None = None,
    threshold_label: str = "",
    colors: list[str] | None = None,
) -> str:
    """Bar ngang cho vài giá trị headline; nhãn giá trị đặt ở đầu bar."""
    label_w, right_pad, row_h, bar_h = 40, 62, 30, 18
    height = row_h * len(items) + 18
    axis_max = max([v for _, v in items] + ([threshold] if threshold else []) + [1]) * 1.15
    plot_w = VIEW_W - label_w - right_pad
    colors = colors or ["var(--series-1)"] * len(items)

    parts = [f'<svg viewBox="0 0 {VIEW_W} {height}" role="img">']
    for index, (name, value) in enumerate(items):
        # 2px surface gap giữa các bar liền kề đến từ khoảng trống row_h - bar_h.
        y = index * row_h + 4
        width = max(0.0, value / axis_max * plot_w)
        tip = f"{name}: {compact(value, 2 if unit == 'usd' else 0)} {unit}"
        parts.append(
            f'<text class="axis-text" x="0" y="{y + bar_h / 2 + 4}">{esc(name)}</text>'
            f'<path class="bar" data-tip="{esc(tip)}" fill="{colors[index]}" '
            f'd="{bar_path(label_w, y, width, bar_h)}"/>'
            f'<text class="value-text" x="{label_w + width + 8}" y="{y + bar_h / 2 + 4}">'
            f"{compact(value, 2 if unit == 'usd' else 0)}</text>"
        )
    if threshold:
        tx = label_w + threshold / axis_max * plot_w
        parts.append(
            f'<line class="threshold-line" x1="{tx}" y1="0" x2="{tx}" y2="{height - 16}"/>'
            f'<text class="threshold-text" x="{tx + 4}" y="{height - 4}">{esc(threshold_label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def columns_over_time(
    buckets: list[tuple[str, float]], unit: str, digits: int = 0, color: str = "var(--series-1)"
) -> str:
    """Cột theo phút cho traffic/cost — trục thời gian, nhãn thưa để không chen nhau."""
    if not buckets:
        return '<p class="empty">Chưa có dữ liệu trong cửa sổ này.</p>'
    height, top_pad, bottom_pad = 150, 14, 24
    y_base = height - bottom_pad
    axis_max = (max(v for _, v in buckets) or 1) * 1.2
    slot = VIEW_W / len(buckets)
    bar_w = min(24.0, max(2.0, slot - 2))  # cap 24px + 2px surface gap giữa cột liền kề

    parts = [f'<svg viewBox="0 0 {VIEW_W} {height}" role="img">']
    for level in (0.5, 1.0):
        y = y_base - level * (y_base - top_pad)
        parts.append(f'<line class="grid-line" x1="0" y1="{y}" x2="{VIEW_W}" y2="{y}"/>')
        parts.append(
            f'<text class="axis-text" x="0" y="{y - 4}">{compact(axis_max * level, digits)}</text>'
        )
    label_every = max(1, len(buckets) // 5)
    for index, (name, value) in enumerate(buckets):
        x = index * slot + (slot - bar_w) / 2
        y_top = y_base - (value / axis_max) * (y_base - top_pad)
        tip = f"{name} · {compact(value, digits)} {unit}"
        parts.append(
            f'<path class="bar" data-tip="{esc(tip)}" fill="{color}" '
            f'd="{column_path(x, y_top, bar_w, y_base)}"/>'
        )
        if index % label_every == 0:
            parts.append(
                f'<text class="axis-text" x="{x + bar_w / 2}" y="{height - 8}" '
                f'text-anchor="middle">{esc(name)}</text>'
            )
    parts.append(f'<line class="baseline" x1="0" y1="{y_base}" x2="{VIEW_W}" y2="{y_base}"/>')
    parts.append("</svg>")
    return "".join(parts)


def meter(value: float, axis_max: float, marker: float, marker_label: str, ok: bool) -> str:
    """Một tỉ lệ so với giới hạn — track là step nhạt cùng ramp, fill mang severity."""
    height, bar_h = 58, 16
    fill_color = "var(--good)" if ok else "var(--critical)"
    width = min(1.0, value / axis_max) * VIEW_W if axis_max else 0
    mx = min(1.0, marker / axis_max) * VIEW_W if axis_max else 0
    # Nhãn ngưỡng bám mốc nhưng không được tràn mép phải.
    label_x, anchor = (mx + 5, "start") if mx < VIEW_W * 0.62 else (mx - 5, "end")
    return (
        f'<svg viewBox="0 0 {VIEW_W} {height}" role="img">'
        f'<path fill="var(--track)" d="{bar_path(0, 20, VIEW_W, bar_h)}"/>'
        f'<path fill="{fill_color}" d="{bar_path(0, 20, max(width, 0), bar_h)}"/>'
        f'<line class="threshold-line" x1="{mx}" y1="14" x2="{mx}" y2="{20 + bar_h + 4}"/>'
        f'<text class="threshold-text" x="{label_x}" y="10" text-anchor="{anchor}">'
        f"{esc(marker_label)}</text>"
        f'<text class="axis-text" x="0" y="{height - 4}">0</text>'
        f'<text class="axis-text" x="{VIEW_W}" y="{height - 4}" text-anchor="end">'
        f"{compact(axis_max, 2)}</text>"
        "</svg>"
    )


# ------------------------------------------------------------------------ panels


def render_panel(panel: dict, data: dict, meta: dict) -> str:
    pid = panel["id"]
    unit = panel["unit"]
    th = panel["threshold"]
    limit, operator, agg = th["value"], th["operator"], th["aggregation"]
    op_text = "≤" if operator == "lte" else "≥"
    body, sub, chip = "", "", ""

    if pid == "latency":
        values = data["latency"]["values"]
        ok, verdict = threshold_state(values["p95"], operator, limit)
        sub = f"{data['latency']['sample_size']} response · SLO: p95 {op_text} {limit:,.0f} ms"
        chip = status_chip(ok, f"p95 = {values['p95']:,.0f} ms — {verdict}")
        body = horizontal_bars(
            [("P50", values["p50"]), ("P95", values["p95"]), ("P99", values["p99"])],
            unit,
            threshold=float(limit),
            threshold_label=f"SLO {limit:,.0f} ms",
        )
        body += table_view(
            ["Percentile", "Latency (ms)"],
            [[k.upper(), f"{v:,.0f}"] for k, v in values.items()],
        )

    elif pid == "traffic":
        traffic = data["traffic"]
        ok, verdict = threshold_state(traffic["rate_per_minute"], operator, limit)
        sub = f"{traffic['count']} request · ngưỡng: {op_text} {limit} req/phút"
        chip = status_chip(ok, f"{traffic['rate_per_minute']} req/phút — {verdict}")
        body = columns_over_time(traffic["buckets"], "request")
        body += table_view(
            ["Phút (UTC)", "Số request"],
            [[m, f"{int(v)}"] for m, v in traffic["buckets"]],
        )

    elif pid == "errors":
        errors = data["errors"]
        ok, verdict = threshold_state(errors["error_rate_pct"], operator, limit)
        sub = (
            f"{errors['failed']}/{errors['received']} request lỗi · "
            f"SLO: {op_text} {limit}%"
        )
        chip = status_chip(ok, f"{errors['error_rate_pct']}% — {verdict}")
        body = (
            f'<p class="hero">{errors["error_rate_pct"]}%</p>'
            f'<p class="hero-note">error rate trong cửa sổ {meta["window_minutes"]} phút</p>'
            + meter(errors["error_rate_pct"], max(limit * 2, 1), float(limit), f"SLO {limit}%", ok)
        )
        if errors["breakdown"]:
            body += table_view(
                ["Loại lỗi", "Số lần"],
                [[k, str(v)] for k, v in errors["breakdown"].most_common()],
                caption="Breakdown theo error_type",
            )
        else:
            body += '<p class="empty">Không có request_failed nào — breakdown rỗng.</p>'

    elif pid == "cost":
        cost = data["cost"]
        ok, verdict = threshold_state(cost["total"], operator, limit)
        sub = f"Tổng cửa sổ · ngân sách: {op_text} ${limit}"
        chip = status_chip(ok, f"${cost['total']:.4f} — {verdict}")
        body = (
            f'<p class="hero">${cost["total"]:.4f}</p>'
            f'<p class="hero-note">tổng chi phí · {meta["responses"]} response</p>'
            + columns_over_time(cost["buckets"], "USD", digits=4, color="var(--series-1)")
        )
        body += table_view(
            ["Phút (UTC)", "Cost (USD)"],
            [[m, f"{v:.6f}"] for m, v in cost["buckets"]],
        )

    elif pid == "tokens":
        tokens = data["tokens"]
        worst = max(tokens["tokens_in"], tokens["tokens_out"])
        ok, verdict = threshold_state(worst, operator, limit)
        sub = f"Tổng theo từng field · ngưỡng: mỗi field {op_text} {limit:,} tokens"
        chip = status_chip(ok, f"max {worst:,} tokens — {verdict}")
        body = (
            '<div class="legend">'
            '<span class="legend-item"><span class="legend-key" '
            'style="background:var(--series-1)"></span>tokens_in</span>'
            '<span class="legend-item"><span class="legend-key" '
            'style="background:var(--series-2)"></span>tokens_out</span>'
            "</div>"
            + horizontal_bars(
                [("Input", tokens["tokens_in"]), ("Output", tokens["tokens_out"])],
                unit,
                colors=["var(--series-1)", "var(--series-2)"],
            )
        )
        body += table_view(
            ["Field", "Tokens"],
            [["tokens_in", f"{tokens['tokens_in']:,}"], ["tokens_out", f"{tokens['tokens_out']:,}"]],
        )

    elif pid == "quality":
        quality = data["quality"]
        ok, verdict = threshold_state(quality["mean"], operator, limit)
        sub = f"{quality['sample_size']} response · SLO: trung bình {op_text} {limit}"
        chip = status_chip(ok, f"{quality['mean']:.2f} — {verdict}")
        body = (
            f'<p class="hero">{quality["mean"]:.2f}</p>'
            f'<p class="hero-note">quality proxy trung bình (thang 0–1)</p>'
            + meter(quality["mean"], 1.0, float(limit), f"SLO {limit}", ok)
        )
        body += table_view(
            ["Chỉ số", "Giá trị"],
            [["mean(quality_score)", f"{quality['mean']:.4f}"], ["Số mẫu", str(quality["sample_size"])]],
        )

    return (
        f'<section class="panel">'
        f'<div class="panel-head"><h2 class="panel-title">{esc(panel["title"])}</h2>'
        f'<span class="panel-unit">{esc(unit)}</span></div>'
        f'<p class="panel-sub">{esc(sub)} · agg <code>{esc(agg)}</code></p>'
        f"{chip}{body}</section>"
    )


def render_html(config: dict, data: dict, window: tuple[datetime, datetime], source: Path) -> str:
    dashboard = config["dashboard"]
    start, end = window
    meta = data["_meta"]
    # Hiển thị đường dẫn tương đối: file này được commit nên không nhúng path máy cá nhân.
    try:
        source_label = source.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        source_label = source.name
    panels = "".join(render_panel(p, data, meta) for p in dashboard["panels"])
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{dashboard['refresh_seconds']}">
<title>{esc(dashboard['title'])}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>{esc(dashboard['title'])}</h1>
  <p class="meta">
    Time range: <strong>{dashboard['time_range_minutes']} phút</strong>
    ({start.strftime('%H:%M:%S')} → {end.strftime('%H:%M:%S')} UTC) ·
    Auto refresh: <strong>{dashboard['refresh_seconds']}s</strong><br>
    Nguồn dữ liệu: <code>{esc(source_label)}</code> ·
    Contract: <code>config/dashboard.yaml</code> (schema_version {dashboard['schema_version']}) ·
    Sinh lúc {generated}
  </p>
</header>
<main class="grid">{panels}</main>
<footer>
  Mỗi panel hiển thị đơn vị, ngưỡng SLO và trạng thái đạt/vi phạm bằng icon + nhãn
  (không dựa vào màu đơn lẻ). Bấm “Bảng dữ liệu” trong từng panel để xem số gốc.
</footer>
<div id="tip" role="status"></div>
<script>{TOOLTIP_JS}</script>
</body>
</html>
"""


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", type=Path, default=DEFAULT_LOGS)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--open", action="store_true", help="Mở dashboard sau khi dựng")
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    window_minutes = config["dashboard"]["time_range_minutes"]

    records = load_records(args.logs)
    inside, start, end = select_window(records, window_minutes)
    data = compute_panels(inside, window_minutes, start, end)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(config, data, (start, end), args.logs), encoding="utf-8")

    print(f"Đã dựng {len(config['dashboard']['panels'])} panel từ {len(inside)} bản ghi.")
    print(f"Cửa sổ: {start:%Y-%m-%d %H:%M:%S} → {end:%H:%M:%S} UTC ({window_minutes} phút)")
    print(f"Output: {args.output}")
    if args.open:
        webbrowser.open(args.output.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
