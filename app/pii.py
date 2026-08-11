from __future__ import annotations

import hashlib
import re

PII_PATTERNS: dict[str, str] = {
    "email": r"[\w\.-]+@[\w\.-]+\.\w+",
    "phone_vn": r"(?<!\d)(?:\+84|0)(?:[ .-]?\d){9}(?!\d)",
    "cccd": r"\b\d{12}\b",
    "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
    # Vietnamese passport letters are uppercase. Keeping this case-sensitive
    # avoids treating generated correlation IDs such as req-c0391357 as PII.
    "passport": r"\b[A-Z]{1,2}\d{7}\b",
    "address_vn": (
        r"(?i:(?:địa\s*chỉ|dia\s*chi)\s*:\s*[^,;\n]+"
        r"|\b(?:số|so)\s+\d+[A-Z]?(?:[ /-]\d+)?\s+[^,;\n]+"
        r"|\b(?:đường|duong|phường|phuong|quận|quan|huyện|huyen)\s+[^,;\n]+)"
    ),
}


def scrub_text(text: str) -> str:
    safe = text
    for name, pattern in PII_PATTERNS.items():
        safe = re.sub(pattern, f"[REDACTED_{name.upper()}]", safe)
    return safe


def summarize_text(text: str, max_len: int = 80) -> str:
    safe = scrub_text(text).strip().replace("\n", " ")
    return safe[:max_len] + ("..." if len(safe) > max_len else "")


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
