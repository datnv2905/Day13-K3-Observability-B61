"""Quản lý prompt version trên Langfuse theo docs/PROMPT_VERSIONING.md.

Các bước trong tài liệu được gói lại thành subcommand để mọi lần chạy đều
lặp lại được và in ra đúng ID cần dán vào submission/REPORT.md.

    python scripts/prompt_versions.py setup      # buoc 1-2: tao v1 + v2
    python scripts/prompt_versions.py list       # xem version va label hien tai
    python scripts/prompt_versions.py compare    # buoc 3-4: 2 label, 2 trace ID
    python scripts/prompt_versions.py promote --version 2   # buoc 5
    python scripts/prompt_versions.py rollback --version 1  # buoc 6
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

from app.cli import configure_utf8_stdio  # noqa: E402
from app.prompt_management import DEFAULT_PROMPT_TEMPLATE, resolve_prompt  # noqa: E402
from app.tracing import get_langfuse_client, observe, tracing_enabled  # noqa: E402

# v2 chỉ đổi format/độ dài câu trả lời; ba biến bắt buộc phải giữ nguyên.
CANDIDATE_PROMPT_TEMPLATE = (
    "Feature={{feature}}\n"
    "Docs={{docs}}\n"
    "Question={{message}}\n"
    "Answer in at most three sentences and cite the doc you used."
)

SAMPLE_INPUT = {
    "user_id": "prompt-compare-01",
    "session_id": "prompt-compare-s01",
    "feature": "qa",
    "message": "What is your refund policy?",
}


def _prompt_name() -> str:
    return os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")


def _require_tracing() -> None:
    if not tracing_enabled():
        print(
            "Langfuse chưa bật. Điền LANGFUSE_PUBLIC_KEY và LANGFUSE_SECRET_KEY vào .env "
            "rồi chạy lại.\nKhông có key thì app vẫn chạy bằng prompt local nhưng không có "
            "evidence trace/prompt version."
        )
        raise SystemExit(1)


def cmd_setup(_: argparse.Namespace) -> None:
    """Bước 1-2: v1 mang label baseline + production, v2 mang label candidate."""
    _require_tracing()
    client = get_langfuse_client()
    name = _prompt_name()

    v1 = client.create_prompt(
        name=name,
        type="text",
        prompt=DEFAULT_PROMPT_TEMPLATE,
        labels=["baseline", "production"],
    )
    print(f"[v{v1.version}] labels=baseline,production")

    v2 = client.create_prompt(
        name=name,
        type="text",
        prompt=CANDIDATE_PROMPT_TEMPLATE,
        labels=["candidate"],
    )
    print(f"[v{v2.version}] labels=candidate")
    print(
        "\nMỗi lần chạy setup đều tạo version mới vì prompt trên Langfuse là immutable.\n"
        "Chạy 'list' để xác nhận label đang trỏ vào version nào."
    )


def cmd_list(_: argparse.Namespace) -> None:
    """In version đang gắn với từng label để đối chiếu trước/sau khi đổi label."""
    _require_tracing()
    client = get_langfuse_client()
    name = _prompt_name()

    for label in ("production", "baseline", "candidate"):
        try:
            prompt = client.get_prompt(name, label=label, type="text", cache_ttl_seconds=0)
            print(f"{label:<11} -> v{prompt.version}")
        except Exception as exc:
            print(f"{label:<11} -> (chưa có) {type(exc).__name__}")


@observe(name="prompt-version-compare")
def _run_once(label: str) -> tuple[str | None, str, str]:
    """Chạy agent thật để tạo trace, trả về trace ID và version đã resolve."""
    from app.agent import LabAgent

    os.environ["LANGFUSE_PROMPT_LABEL"] = label
    client = get_langfuse_client()

    resolved = resolve_prompt(
        client,
        feature=SAMPLE_INPUT["feature"],
        docs=[],
        message=SAMPLE_INPUT["message"],
        enabled=True,
    )
    LabAgent().run(**SAMPLE_INPUT)
    return client.get_current_trace_id(), resolved.version, resolved.source


def cmd_compare(_: argparse.Namespace) -> None:
    """Bước 3-4: cùng một input, hai label, hai trace ID."""
    _require_tracing()
    original_label = os.getenv("LANGFUSE_PROMPT_LABEL", "production")
    client = get_langfuse_client()

    print(f'Input: "{SAMPLE_INPUT["message"]}"\n')
    results = []
    try:
        for label in ("baseline", "candidate"):
            trace_id, version, source = _run_once(label)
            results.append((label, version, source, trace_id))
            print(f"label={label:<9} version={version:<9} source={source:<15} trace_id={trace_id}")
    finally:
        os.environ["LANGFUSE_PROMPT_LABEL"] = original_label
        client.flush()

    if any(source != "langfuse" for _, _, source, _ in results):
        print(
            "\nCảnh báo: có run rơi về prompt local. Kiểm tra host/key và prompt name/label "
            "trong .env, trace này chưa dùng được làm evidence."
        )
        return

    print("\nDán hai trace ID trên vào mục 4 của submission/REPORT.md.")


def _move_production_label(version: int, action: str) -> None:
    _require_tracing()
    client = get_langfuse_client()
    name = _prompt_name()

    try:
        current = client.get_prompt(name, label="production", type="text", cache_ttl_seconds=0)
        print(f"Trước: production -> v{current.version}")
    except Exception as exc:
        print(f"Trước: production -> (chưa có) {type(exc).__name__}")

    client.update_prompt(name=name, version=version, new_labels=["production"])
    print(f"Sau:   production -> v{version}  ({action})")
    print("Chụp màn hình danh sách version trước/sau bước này làm evidence.")


def cmd_promote(args: argparse.Namespace) -> None:
    """Bước 5: chuyển label production sang version mới."""
    _move_production_label(args.version, "promote")


def cmd_rollback(args: argparse.Namespace) -> None:
    """Bước 6: trả label production về version cũ."""
    _move_production_label(args.version, "rollback")


def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Quản lý prompt version trên Langfuse theo docs/PROMPT_VERSIONING.md."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup", help="Tạo prompt v1 (baseline+production) và v2 (candidate)")
    subparsers.add_parser("list", help="In version đang gắn với mỗi label")
    subparsers.add_parser("compare", help="Chạy cùng input với label baseline và candidate")

    promote = subparsers.add_parser("promote", help="Chuyển label production sang version khác")
    promote.add_argument("--version", type=int, required=True)

    rollback = subparsers.add_parser("rollback", help="Trả label production về version cũ")
    rollback.add_argument("--version", type=int, required=True)

    args = parser.parse_args()
    {
        "setup": cmd_setup,
        "list": cmd_list,
        "compare": cmd_compare,
        "promote": cmd_promote,
        "rollback": cmd_rollback,
    }[args.command](args)


if __name__ == "__main__":
    main()
