"""ISO datetime parsing for MCP tool arguments."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def _parse_iso_text(value: str, *, end_of_day: bool = False) -> datetime:
    text = (value or "").strip()
    if not text:
        raise ValueError("empty datetime")
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    parsed = datetime.fromisoformat(text)
    if end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed


def parse_iso_datetime(value: str, *, end_of_day: bool = False) -> datetime:
    parsed = _parse_iso_text(value, end_of_day=end_of_day)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_scheduling_datetime(
    value: str,
    timezone: ZoneInfo,
    *,
    end_of_day: bool = False,
) -> datetime:
    """Parse ISO input for scheduling; naive values use the given IANA timezone."""
    parsed = _parse_iso_text(value, end_of_day=end_of_day)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)
