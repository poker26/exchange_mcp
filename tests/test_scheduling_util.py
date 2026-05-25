from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from exchange_mcp.backends.base import AttendeeAvailability, BusyInterval
from exchange_mcp.scheduling_util import (
    SchedulingError,
    collect_unique_emails,
    parse_accepted_domains,
    pick_preferred_email,
    suggest_meeting_times,
    validate_attendee_list,
)


def test_normalize_smtp_prefix_and_lowercase():
    from exchange_mcp.scheduling_util import normalize_email_address

    assert normalize_email_address("SMTP:User@Fin-Frame.RU") == "user@fin-frame.ru"


def test_parse_accepted_domains():
    assert parse_accepted_domains(
        "fin-frame.ru, @inplatlabs.ru ,instant-pay.ru",
    ) == ["fin-frame.ru", "inplatlabs.ru", "instant-pay.ru"]


def test_collect_unique_emails_skips_invalid():
    emails = collect_unique_emails([
        "SMTP:a@fin-frame.ru",
        "a@fin-frame.ru",
        "not-an-email",
    ])
    assert emails == ["a@fin-frame.ru"]


def test_pick_preferred_email_uses_accepted_domains_order():
    emails = [
        "user@instant-pay.ru",
        "user@inplatlabs.ru",
        "user@fin-frame.ru",
    ]
    preferred = pick_preferred_email(
        emails,
        "org@fin-frame.ru",
        ["fin-frame.ru", "inplatlabs.ru"],
    )
    assert preferred == "user@fin-frame.ru"


def test_pick_preferred_email_falls_back_to_second_domain():
    emails = ["user@instant-pay.ru", "user@inplatlabs.ru"]
    preferred = pick_preferred_email(
        emails,
        "org@fin-frame.ru",
        ["fin-frame.ru", "inplatlabs.ru"],
    )
    assert preferred == "user@inplatlabs.ru"


def test_validate_attendee_list_deduplicates_organizer():
    attendees = validate_attendee_list(
        ["colleague@fin-frame.ru", "ORG@fin-frame.ru"],
        "org@fin-frame.ru",
    )
    assert attendees == ["org@fin-frame.ru", "colleague@fin-frame.ru"]


def test_suggest_meeting_times_finds_free_slot():
    timezone_moscow = ZoneInfo("Europe/Moscow")
    window_start = datetime(2026, 5, 26, 9, 0, tzinfo=timezone_moscow)
    window_end = datetime(2026, 5, 26, 12, 0, tzinfo=timezone_moscow)
    busy_start = datetime(2026, 5, 26, 10, 0, tzinfo=timezone_moscow)
    busy_end = datetime(2026, 5, 26, 11, 0, tzinfo=timezone_moscow)
    availability = [
        AttendeeAvailability(
            email="a@fin-frame.ru",
            role="required",
            calendar_status="ok",
            busy=[BusyInterval(start=busy_start, end=busy_end, status="busy")],
        ),
        AttendeeAvailability(
            email="b@fin-frame.ru",
            role="required",
            calendar_status="ok",
            busy=[],
        ),
    ]

    suggestions, partial, unresolved = suggest_meeting_times(
        availability,
        window_start=window_start,
        window_end=window_end,
        duration_minutes=60,
        max_suggestions=5,
        working_start=(9, 0),
        working_end=(18, 0),
        working_days=("monday", "tuesday", "wednesday", "thursday", "friday"),
    )

    assert partial is False
    assert unresolved == []
    assert suggestions
    first_slot = suggestions[0]
    assert first_slot.start == window_start
    assert first_slot.all_attendees_free is True


def test_suggest_meeting_times_invalid_duration():
    timezone_moscow = ZoneInfo("Europe/Moscow")
    window_start = datetime(2026, 5, 26, 9, 0, tzinfo=timezone_moscow)
    window_end = datetime(2026, 5, 26, 18, 0, tzinfo=timezone_moscow)
    with pytest.raises(SchedulingError) as exc_info:
        suggest_meeting_times(
            [],
            window_start=window_start,
            window_end=window_end,
            duration_minutes=5,
            max_suggestions=1,
            working_start=(9, 0),
            working_end=(18, 0),
            working_days=("monday",),
        )
    assert exc_info.value.code == "INVALID_DURATION"
