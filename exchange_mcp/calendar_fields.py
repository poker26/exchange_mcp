"""EWS calendar view field profiles with server-side fallback."""
from __future__ import annotations

from typing import Callable, TypeVar

from .backends.base import BackendError

CalendarViewResult = tuple[list, str, list[str]]

_CALENDAR_FIELDS_FULL: tuple[str, ...] = (
    "id",
    "uid",
    "subject",
    "location",
    "organizer",
    "start",
    "end",
    "last_modified_time",
    "is_all_day",
    "body",
    "required_attendees",
    "optional_attendees",
    "is_cancelled",
    "type",
    "is_recurring",
)

_CALENDAR_FIELDS_STANDARD: tuple[str, ...] = (
    "id",
    "uid",
    "subject",
    "location",
    "organizer",
    "start",
    "end",
    "last_modified_time",
    "is_all_day",
    "is_cancelled",
    "type",
    "is_recurring",
)

_CALENDAR_FIELDS_MINIMAL: tuple[str, ...] = (
    "id",
    "uid",
    "subject",
    "location",
    "organizer",
    "start",
    "end",
    "last_modified_time",
    "is_all_day",
    "is_cancelled",
    "type",
)

CALENDAR_FIELD_PROFILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("full", _CALENDAR_FIELDS_FULL),
    ("standard", _CALENDAR_FIELDS_STANDARD),
    ("minimal", _CALENDAR_FIELDS_MINIMAL),
)

EventType = TypeVar("EventType")


def is_unsupported_calendar_field_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return (
        "unknown field path" in message
        or "invalid field" in message
        or "field path" in message and "unknown" in message
    )


def fetch_calendar_view_events(
    folder,
    *,
    start_ews,
    end_ews,
    limit: int,
    to_calendar_item: Callable[[EventType, bool], object],
) -> tuple[list, str, list[str]]:
    """Load calendar items trying field profiles from full to minimal."""
    warnings: list[str] = []
    last_error: BaseException | None = None

    for profile_name, field_names in CALENDAR_FIELD_PROFILES:
        try:
            query_set = (
                folder.view(start=start_ews, end=end_ews)
                .only(*field_names)
            )
            query_set = query_set[: max(1, min(limit, 500))]
            raw_events = list(query_set)
            attendees_loaded = profile_name == "full"
            return [
                to_calendar_item(event, attendees_loaded)
                for event in raw_events
            ], profile_name, warnings
        except Exception as exc:
            if is_unsupported_calendar_field_error(exc):
                warnings.append(
                    f"skipped fields_profile={profile_name!r}: {exc}",
                )
                last_error = exc
                continue
            raise BackendError(f"get_calendar_items: {exc}") from exc

    if last_error is not None:
        raise BackendError(f"get_calendar_items: {last_error}") from last_error
    raise BackendError("get_calendar_items: no calendar field profile succeeded")
