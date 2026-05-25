"""Meeting scheduling helpers: validation, free/busy merge, slot suggestions."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .backends.base import AttendeeAvailability, BusyInterval, MeetingSuggestion
from .datetime_util import parse_scheduling_datetime

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_AVAILABILITY_DAYS = 14
_SUGGEST_GRID_MINUTES = 15
_BUSY_STATUSES = frozenset({
    "busy",
    "tentative",
    "oof",
    "working_elsewhere",
    "no_data",
})
_WEEKDAY_ALIASES = {
    "mon": "monday",
    "monday": "monday",
    "tue": "tuesday",
    "tues": "tuesday",
    "tuesday": "tuesday",
    "wed": "wednesday",
    "wednesday": "wednesday",
    "thu": "thursday",
    "thur": "thursday",
    "thurs": "thursday",
    "thursday": "thursday",
    "fri": "friday",
    "friday": "friday",
    "sat": "saturday",
    "saturday": "saturday",
    "sun": "sunday",
    "sunday": "sunday",
}
_DEFAULT_WORKING_DAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
)


class SchedulingError(Exception):
    """Predictable scheduling validation failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def normalize_smtp_address(value: str) -> str:
    text = (value or "").strip()
    if text.upper().startswith("SMTP:"):
        text = text[5:].strip()
    return text.lower()


def normalize_email_address(value: str) -> str:
    return normalize_smtp_address(value)


def collect_unique_emails(raw_addresses: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw_address in raw_addresses:
        normalized = normalize_email_address(raw_address)
        if not normalized or normalized in seen:
            continue
        if not is_valid_email_address(normalized):
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def pick_preferred_email(emails: list[str], organizer_email: str) -> str:
    if not emails:
        return ""
    organizer_normalized = normalize_email_address(organizer_email)
    organizer_domain = (
        organizer_normalized.split("@")[-1]
        if "@" in organizer_normalized
        else ""
    )
    if organizer_domain:
        for email in emails:
            if email.split("@")[-1] == organizer_domain:
                return email
    return emails[0]


def is_valid_email_address(value: str) -> bool:
    normalized = normalize_email_address(value)
    return bool(normalized) and bool(_EMAIL_PATTERN.match(normalized))


def dedupe_attendee_emails(
    attendees: list[str],
    organizer_email: str,
) -> list[str]:
    organizer_normalized = normalize_email_address(organizer_email)
    seen: set[str] = set()
    result: list[str] = []
    if organizer_normalized:
        seen.add(organizer_normalized)
        result.append(organizer_normalized)
    for raw_address in attendees:
        normalized = normalize_email_address(raw_address)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def parse_working_time_hhmm(value: str, *, field_name: str) -> tuple[int, int]:
    text = (value or "").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        raise SchedulingError(
            "INVALID_WORKING_HOURS",
            f"{field_name} must be HH:MM, got {value!r}",
        )
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise SchedulingError(
            "INVALID_WORKING_HOURS",
            f"{field_name} out of range: {value!r}",
        )
    return hour, minute


def normalize_working_days(values: Optional[list[str]]) -> tuple[str, ...]:
    if not values:
        return _DEFAULT_WORKING_DAYS
    normalized: list[str] = []
    for raw_day in values:
        key = (raw_day or "").strip().lower()
        mapped = _WEEKDAY_ALIASES.get(key)
        if mapped is None:
            allowed = ", ".join(sorted(set(_WEEKDAY_ALIASES.values())))
            raise SchedulingError(
                "INVALID_WORKING_DAYS",
                f"working_days entry {raw_day!r} invalid; use: {allowed}",
            )
        if mapped not in normalized:
            normalized.append(mapped)
    return tuple(normalized)


def validate_availability_window(
    date_from: str,
    date_to: str,
    timezone_name: str,
) -> tuple[datetime, datetime, ZoneInfo]:
    try:
        timezone = ZoneInfo(timezone_name)
    except Exception as exc:
        raise SchedulingError(
            "INVALID_TIMEZONE",
            f"unknown timezone {timezone_name!r}: {exc}",
        ) from exc

    start = parse_scheduling_datetime(date_from, timezone)
    end = parse_scheduling_datetime(date_to, timezone, end_of_day="T" not in date_to.strip())
    if end <= start:
        raise SchedulingError("INVALID_TIME_RANGE", "date_to must be after date_from")
    if end - start > timedelta(days=_MAX_AVAILABILITY_DAYS):
        raise SchedulingError(
            "INVALID_TIME_RANGE",
            f"availability window cannot exceed {_MAX_AVAILABILITY_DAYS} days",
        )
    return start, end, timezone


def validate_attendee_list(attendees: list[str], organizer_email: str) -> list[str]:
    if not attendees:
        raise SchedulingError("INVALID_ATTENDEE", "attendees list is empty")
    normalized = dedupe_attendee_emails(attendees, organizer_email)
    if len(normalized) > 100:
        raise SchedulingError("TOO_MANY_ATTENDEES", "at most 100 attendees per request")
    invalid = [address for address in normalized if not is_valid_email_address(address)]
    if invalid:
        raise SchedulingError(
            "INVALID_ATTENDEE",
            f"invalid email address(es): {', '.join(invalid)}",
        )
    return normalized


def map_ews_busy_status(raw_status: str) -> str:
    normalized = (raw_status or "Busy").strip()
    mapping = {
        "Free": "free",
        "Tentative": "tentative",
        "Busy": "busy",
        "OOF": "oof",
        "NoData": "no_data",
        "WorkingElsewhere": "working_elsewhere",
    }
    return mapping.get(normalized, "busy")


def minutes_since_midnight_to_hhmm(minutes_value) -> str:
    if hasattr(minutes_value, "hour") and hasattr(minutes_value, "minute"):
        return f"{int(minutes_value.hour):02d}:{int(minutes_value.minute):02d}"
    total_minutes = int(minutes_value)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def weekday_names_to_strings(weekday_values) -> list[str]:
    result: list[str] = []
    for weekday in weekday_values or []:
        name = str(weekday).strip().lower()
        if name.endswith("day"):
            result.append(name)
        else:
            mapped = _WEEKDAY_ALIASES.get(name[:3], name)
            if mapped not in result:
                result.append(mapped)
    return result


def attendee_blocks_slot(attendee: AttendeeAvailability, slot_start: datetime, slot_end: datetime) -> bool:
    if attendee.calendar_status in ("external", "not_found"):
        return False
    if attendee.calendar_status != "ok":
        return True
    for interval in attendee.busy:
        if interval.status not in _BUSY_STATUSES:
            continue
        if interval.start < slot_end and interval.end > slot_start:
            return True
    return False


def is_within_working_hours(
    slot_start: datetime,
    slot_end: datetime,
    *,
    working_start: tuple[int, int],
    working_end: tuple[int, int],
    working_days: tuple[str, ...],
) -> bool:
    weekday = slot_start.strftime("%A").lower()
    if weekday not in working_days:
        return False
    day_start = slot_start.replace(
        hour=working_start[0],
        minute=working_start[1],
        second=0,
        microsecond=0,
    )
    day_end = slot_start.replace(
        hour=working_end[0],
        minute=working_end[1],
        second=0,
        microsecond=0,
    )
    return slot_start >= day_start and slot_end <= day_end


def suggest_meeting_times(
    availability: list[AttendeeAvailability],
    *,
    window_start: datetime,
    window_end: datetime,
    duration_minutes: int,
    max_suggestions: int,
    working_start: tuple[int, int],
    working_end: tuple[int, int],
    working_days: tuple[str, ...],
    buffer_minutes: int = 0,
) -> tuple[list[MeetingSuggestion], bool, list[str]]:
    if duration_minutes < 15 or duration_minutes > 480:
        raise SchedulingError(
            "INVALID_DURATION",
            "duration_minutes must be between 15 and 480",
        )

    unresolved = [
        attendee.email
        for attendee in availability
        if attendee.calendar_status in ("not_found", "external", "error")
    ]
    partial = any(
        attendee.calendar_status not in ("ok",)
        for attendee in availability
    )

    step = timedelta(minutes=_SUGGEST_GRID_MINUTES)
    slot_duration = timedelta(minutes=duration_minutes)
    buffer_delta = timedelta(minutes=max(0, buffer_minutes))

    suggestions: list[MeetingSuggestion] = []
    cursor = window_start
    while cursor + slot_duration <= window_end:
        slot_end = cursor + slot_duration
        if not is_within_working_hours(
            cursor,
            slot_end,
            working_start=working_start,
            working_end=working_end,
            working_days=working_days,
        ):
            cursor += step
            continue

        blocked_attendees: list[str] = []
        unknown_attendees: list[str] = []
        for attendee in availability:
            expanded_start = cursor - buffer_delta
            expanded_end = slot_end + buffer_delta
            if attendee.calendar_status in ("external", "not_found"):
                unknown_attendees.append(attendee.email)
                continue
            if attendee_blocks_slot(attendee, expanded_start, expanded_end):
                blocked_attendees.append(attendee.email)

        if blocked_attendees:
            cursor += step
            continue

        all_free = len(unknown_attendees) == 0
        score = 1.0 if all_free else 0.8
        suggestions.append(MeetingSuggestion(
            start=cursor,
            end=slot_end,
            score=score,
            all_attendees_free=all_free,
        ))

        cursor += step

    suggestions.sort(key=lambda item: (-item.score, item.start))
    return suggestions[:max_suggestions], partial, unresolved
