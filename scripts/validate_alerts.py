"""Kiểm tra SLO và alert rules có nhất quán với dashboard contract không.

Cùng một ngưỡng đang nằm ở ba chỗ: config/slo.yaml, config/alert_rules.yaml và
config/dashboard.yaml. Sửa một chỗ quên hai chỗ kia là lỗi im lặng — dashboard báo
"đạt" trong khi alert đã kêu, hoặc ngược lại. Script này bắt đúng loại lệch đó.

    python scripts/validate_alerts.py
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio

REQUIRED_ALERT_FIELDS = ("name", "severity", "condition", "type", "owner", "runbook")
VALID_SEVERITIES = {"info", "warning", "critical"}

# SLI nào tương ứng threshold của panel nào trong dashboard contract.
SLI_TO_PANEL = {
    "latency_p95_ms": "latency",
    "error_rate_pct": "errors",
    # Tên SLI phải khớp config/slo.yaml. Trước đây ghi 'daily_cost_usd' nên
    # validator báo lỗi ngay cả khi config đúng.
    "cost_total_usd": "cost",
    "quality_score_avg": "quality",
}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def condition_threshold(condition: str) -> float | None:
    """Lấy con số sau dấu so sánh trong condition, ví dụ '... > 3000ms ...' -> 3000."""
    match = re.search(r"[<>]=?\s*([0-9]+(?:\.[0-9]+)?)", condition)
    return float(match.group(1)) if match else None


def check(config_dir: Path, docs_dir: Path) -> list[str]:
    problems: list[str] = []

    slo = load_yaml(config_dir / "slo.yaml")
    alerts_doc = load_yaml(config_dir / "alert_rules.yaml")
    dashboard = load_yaml(config_dir / "dashboard.yaml")["dashboard"]

    slis = slo.get("slis") or {}
    panels = {panel["id"]: panel for panel in dashboard["panels"]}
    runbook_text = (docs_dir / "alerts.md").read_text(encoding="utf-8")

    # 1. SLO đã điền chưa và có khớp threshold của dashboard không.
    for sli_name, panel_id in SLI_TO_PANEL.items():
        sli = slis.get(sli_name)
        if not isinstance(sli, dict):
            problems.append(f"slo.yaml thiếu SLI '{sli_name}'")
            continue
        objective = sli.get("objective")
        if not isinstance(objective, (int, float)):
            problems.append(f"slo.yaml: '{sli_name}.objective' phải là số")
            continue
        panel_value = panels[panel_id]["threshold"]["value"]
        if float(objective) != float(panel_value):
            problems.append(
                f"Lệch ngưỡng: slo.yaml '{sli_name}.objective'={objective} "
                f"nhưng dashboard.yaml panel '{panel_id}'={panel_value}"
            )
        if "TODO" in str(sli.get("note", "")):
            problems.append(f"slo.yaml: '{sli_name}.note' còn TODO")

    # 2. Alert rules đã điền chưa.
    alerts = alerts_doc.get("alerts")
    # Yêu cầu của lab là tối thiểu 3 alert. Ghim đúng 3 sẽ chặn nhóm bổ sung
    # alert cho SLI còn lại (ví dụ cost), nên chỉ kiểm tra cận dưới.
    if not isinstance(alerts, list) or len(alerts) < 3:
        problems.append("alert_rules.yaml phải có ít nhất 3 alert")
        return problems

    seen_names: set[str] = set()
    for index, alert in enumerate(alerts):
        label = alert.get("name", f"alerts[{index}]")

        for field in REQUIRED_ALERT_FIELDS:
            value = alert.get(field)
            if value in (None, ""):
                problems.append(f"{label}: thiếu '{field}'")
            elif "TODO" in str(value):
                problems.append(f"{label}: '{field}' còn TODO")

        if alert.get("name") in seen_names:
            problems.append(f"{label}: tên alert bị trùng")
        seen_names.add(alert.get("name"))

        if alert.get("severity") not in VALID_SEVERITIES:
            problems.append(
                f"{label}: severity '{alert.get('severity')}' không hợp lệ "
                f"(chỉ nhận {sorted(VALID_SEVERITIES)})"
            )

        if alert.get("type") != "symptom-based":
            problems.append(f"{label}: type phải là 'symptom-based'")

        # 3. Runbook phải tồn tại thật, không phải link chết.
        runbook = str(alert.get("runbook", ""))
        if "#" in runbook:
            anchor = runbook.split("#", 1)[1]
            heading = "## " + anchor.replace("-", " ").title()
            if heading.lower() not in runbook_text.lower():
                problems.append(f"{label}: docs/alerts.md không có mục '{heading}'")

        # 4. Ngưỡng trong condition phải khớp objective của SLI mà alert trỏ tới.
        sli_name = alert.get("sli")
        if sli_name is None:
            problems.append(f"{label}: thiếu 'sli' nên không truy được về SLO nào")
        elif sli_name not in slis:
            problems.append(f"{label}: 'sli={sli_name}' không có trong slo.yaml")
        else:
            observed = condition_threshold(str(alert.get("condition", "")))
            objective = slis[sli_name].get("objective")
            if observed is None:
                problems.append(f"{label}: không đọc được ngưỡng trong 'condition'")
            elif float(observed) != float(objective):
                problems.append(
                    f"Lệch ngưỡng: {label} condition={observed} "
                    f"nhưng slo.yaml '{sli_name}.objective'={objective}"
                )

    return problems


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=REPO_ROOT / "config")
    parser.add_argument("--docs-dir", type=Path, default=REPO_ROOT / "docs")
    args = parser.parse_args()

    problems = check(args.config_dir, args.docs_dir)
    if problems:
        print("KHÔNG HỢP LỆ:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    total = len(load_yaml(args.config_dir / "alert_rules.yaml").get("alerts") or [])
    print(f"HỢP LỆ: {total} alert rule đã điền, có runbook, và ngưỡng khớp SLO + dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
