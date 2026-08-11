import json

from app.logging_config import scrub_event
from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_event_redacts_top_level_and_nested_values() -> None:
    event = {
        "event": "request_received",
        "session_id": "student@vinuni.edu.vn",
        "payload": {
            "message": "Call 0987654321",
            "nested": {"card": "4111 1111 1111 1111"},
            "items": ["Passport B1234567"],
        },
    }

    scrubbed = scrub_event(None, "info", event)
    serialized = json.dumps(scrubbed)

    for raw_value in (
        "student@vinuni.edu.vn",
        "0987654321",
        "4111 1111 1111 1111",
        "B1234567",
    ):
        assert raw_value not in serialized
    assert "REDACTED_EMAIL" in serialized
    assert "REDACTED_PHONE_VN" in serialized
    assert "REDACTED_CREDIT_CARD" in serialized
    assert "REDACTED_PASSPORT_VN" in serialized
