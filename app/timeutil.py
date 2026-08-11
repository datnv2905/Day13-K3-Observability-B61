"""Múi giờ dùng chung cho log, schema và dashboard.

Toàn hệ thống hiển thị theo giờ Việt Nam nhưng timestamp vẫn mang offset `+07:00`,
không phải giờ "trần" không rõ vùng. Nhờ vậy log cũ ghi bằng UTC (`...Z`) và log mới
vẫn so sánh, sắp xếp được với nhau — `datetime.fromisoformat` đọc cả hai dạng.

Dùng offset cố định thay vì `ZoneInfo("Asia/Ho_Chi_Minh")` vì Việt Nam không có DST
từ 1975, và `zoneinfo` trên Windows còn cần cài thêm gói `tzdata`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

LOCAL_TZ = timezone(timedelta(hours=7), "ICT")
LOCAL_TZ_LABEL = "GMT+7"


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def to_local(moment: datetime) -> datetime:
    """Đưa một mốc thời gian bất kỳ về giờ Việt Nam; mốc naive coi như đã là giờ VN."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=LOCAL_TZ)
    return moment.astimezone(LOCAL_TZ)
