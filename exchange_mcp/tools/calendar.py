"""Calendar tools."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ..backends.base import CalendarUpdateError
from ..clients import router
from ..datetime_util import parse_iso_datetime


def _default_week_range() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    week_end = (week_start + timedelta(days=7)).replace(
        hour=23, minute=59, second=59, microsecond=0,
    )
    return week_start, week_end


def exchange_get_calendar(
    folder_id: Optional[str] = None,
    date_from: str = "",
    date_to: str = "",
) -> dict:
    """Fetch calendar events in a date range.

    Args:
        folder_id: folder id from `exchange_list_folders`; defaults to Calendar.
        date_from: ISO date or datetime (UTC if naive). Empty = Monday 00:00 UTC.
        date_to: ISO date or datetime. Empty = end of current week (Sunday 23:59 UTC).
    """
    if date_from.strip() and date_to.strip():
        start = parse_iso_datetime(date_from)
        end = parse_iso_datetime(date_to, end_of_day="T" not in date_to.strip())
    else:
        start, end = _default_week_range()

    items, backend = router.get_calendar(
        folder_id, start, end, limit=200,
    )
    return {
        "backend": backend,
        "folder_id": folder_id,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "count": len(items),
        "events": [event.to_dict() for event in items],
    }


def exchange_get_new_events(
    folder_id: Optional[str] = None,
    max_items: int = 50,
) -> dict:
    """Return calendar changes since the last call (incremental).

    Returns added, changed, and deleted events. Uses per-calendar-folder
    cursor plus UID + last-modified tracking (EWS).
    """
    max_items = max(1, min(int(max_items), 200))
    added, changed, deleted, backend, is_initial = router.get_new_calendar(
        folder_id, limit=max_items,
    )
    upsert_events = added + changed
    return {
        "backend": backend,
        "folder_id": folder_id,
        "is_initial": is_initial,
        "count": len(upsert_events),
        "added": [event.to_dict() for event in added],
        "changed": [event.to_dict() for event in changed],
        "deleted": deleted,
        "events": [event.to_dict() for event in upsert_events],
    }


def exchange_create_event(
    subject: str,
    start: str,
    end: str,
    location: str = "",
    body: str = "",
    attendees: Optional[list[str]] = None,
) -> dict:
    """Create a calendar event via EWS."""
    event, backend = router.create_calendar_event(
        subject=subject,
        start=start,
        end=end,
        location=location,
        body=body,
        attendees=attendees,
    )
    return {
        "backend": backend,
        "status": "created",
        "event": event.to_dict(),
    }


def exchange_update_event(
    event_id: str,
    start: str = "",
    end: str = "",
    subject: str = "",
    location: str = "",
    body: str = "",
    body_is_html: bool = False,
    send_meeting_invitations: str = "to_all",
) -> dict:
    """Update an existing calendar event (reschedule or edit metadata).

    Args:
        event_id: calendar item id from `exchange_get_calendar` or `exchange_create_event`.
        start: new start in ISO 8601 (naive treated as UTC). Empty = leave unchanged.
        end: new end in ISO 8601. Empty = leave unchanged.
        subject: new title when non-empty; empty = leave unchanged.
        location: new location when non-empty; empty = leave unchanged.
        body: new body when non-empty; empty = leave unchanged (does not clear body).
        body_is_html: use HTML body when `body` is updated.
        send_meeting_invitations: `to_all` (default), `to_changed`, or `save_only`.
    """
    try:
        event, backend = router.update_calendar_event(
            event_id,
            start=start or None,
            end=end or None,
            subject=subject or None,
            location=location or None,
            body=body or None,
            body_is_html=body_is_html,
            send_meeting_invitations=send_meeting_invitations,
        )
    except CalendarUpdateError as exc:
        return {
            "error": True,
            "code": exc.code,
            "message": str(exc),
        }
    return {
        "backend": backend,
        "status": "updated",
        "event": event.to_dict(),
    }


def exchange_respond_to_event(event_id: str, response: str) -> dict:
    """Accept, decline, or tentatively accept a meeting invitation.

    Args:
        event_id: calendar item id from `exchange_get_calendar`.
        response: one of accept, decline, tentative.
    """
    event, backend = router.respond_to_event(event_id, response)
    return {
        "backend": backend,
        "response": response.strip().lower(),
        "status": "sent",
        "event": event.to_dict(),
    }


TOOLS = [
    exchange_get_calendar,
    exchange_get_new_events,
    exchange_create_event,
    exchange_update_event,
    exchange_respond_to_event,
]
