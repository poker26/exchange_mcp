"""ISO datetime parsing for MCP tool arguments."""
from __future__ import annotations

from datetime import datetime, timezone


def parse_iso_datetime(value: str, *, end_of_day: bool = False) -> datetime:
    text = (value or "").strip()
    if not text:
        raise ValueError("empty datetime")
    if "T" in text:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    else:
        parsed = datetime.fromisoformat(text)
        if end_of_day:
            parsed = parsed.replace(hour=23, minute=59, second=59)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
