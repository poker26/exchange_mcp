"""Unit tests for calendar field profile fallback."""
from __future__ import annotations

from exchange_mcp.calendar_fields import (
    CALENDAR_FIELD_PROFILES,
    is_unsupported_calendar_field_error,
)


def test_recurring_master_id_not_in_any_profile() -> None:
    for _profile_name, field_names in CALENDAR_FIELD_PROFILES:
        assert "recurring_master_id" not in field_names


def test_detect_unknown_field_path_error() -> None:
    exc = Exception(
        "Unknown field path 'recurring_master_id' on folders (Calendar(...),)",
    )
    assert is_unsupported_calendar_field_error(exc) is True


def test_other_errors_not_detected() -> None:
    assert is_unsupported_calendar_field_error(Exception("connection reset")) is False
