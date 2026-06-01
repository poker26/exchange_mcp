"""Calendar tools."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ..backends.base import CalendarUpdateError
from ..clients import router
from ..datetime_util import parse_iso_datetime
from ..scheduling_util import SchedulingError


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

    items, backend, fields_profile, warnings = router.get_calendar(
        folder_id, start, end, limit=200,
    )
    response = {
        "backend": backend,
        "folder_id": folder_id,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "count": len(items),
        "fields_profile": fields_profile,
        "events": [event.to_dict() for event in items],
    }
    if warnings:
        response["warnings"] = warnings
    return response


def exchange_get_new_events(
    folder_id: Optional[str] = None,
    max_items: int = 50,
) -> dict:
    """Return calendar changes since the last call (incremental).

    Returns added, changed, and deleted events. Uses per-calendar-folder
    cursor plus UID + last-modified tracking (EWS).
    """
    max_items = max(1, min(int(max_items), 200))
    (
        added,
        changed,
        deleted,
        backend,
        is_initial,
        fields_profile,
        warnings,
    ) = router.get_new_calendar(folder_id, limit=max_items)
    upsert_events = added + changed
    response = {
        "backend": backend,
        "folder_id": folder_id,
        "is_initial": is_initial,
        "count": len(upsert_events),
        "fields_profile": fields_profile,
        "added": [event.to_dict() for event in added],
        "changed": [event.to_dict() for event in changed],
        "deleted": deleted,
        "events": [event.to_dict() for event in upsert_events],
    }
    if warnings:
        response["warnings"] = warnings
    return response


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


def exchange_get_availability(
    attendees: list[str],
    date_from: str,
    date_to: str,
    timezone: str = "",
    granularity_minutes: int = 30,
) -> dict:
    """Free/busy intervals for meeting attendees (EWS GetUserAvailability).

    The organizer mailbox is added automatically when missing from `attendees`.
    Naive ISO datetimes are interpreted in `timezone` (default from CALENDAR_TIMEZONE).

    Args:
        attendees: SMTP addresses (1-100).
        date_from: ISO start of the search window.
        date_to: ISO end of the window (max 14 days from date_from).
        timezone: IANA timezone, e.g. Europe/Moscow.
        granularity_minutes: 15, 30, or 60 (default 30).
    """
    try:
        rows, errors, backend, window_start, window_end, timezone_name = (
            router.get_availability(
                attendees,
                date_from,
                date_to,
                timezone=timezone or None,
                granularity_minutes=granularity_minutes,
            )
        )
    except SchedulingError as exc:
        return {"error": True, "code": exc.code, "message": str(exc)}
    return {
        "backend": backend,
        "timezone": timezone_name,
        "date_from": window_start.isoformat(),
        "date_to": window_end.isoformat(),
        "granularity_minutes": granularity_minutes,
        "attendees": [row.to_dict() for row in rows],
        "errors": errors,
    }


def exchange_suggest_meeting_times(
    attendees: list[str],
    date_from: str,
    date_to: str,
    duration_minutes: int,
    timezone: str = "",
    max_suggestions: int = 5,
    working_hours_start: str = "09:00",
    working_hours_end: str = "18:00",
    working_days: Optional[list[str]] = None,
    buffer_minutes: int = 0,
) -> dict:
    """Suggest meeting slots when all attendees are free.

    Resolves free/busy internally, then finds overlapping slots inside working hours.
    Prefer this over manual calendar inspection for scheduling requests.

    Args:
        attendees: SMTP addresses; organizer is auto-included.
        date_from: ISO start of search window.
        date_to: ISO end (max 14 days).
        duration_minutes: meeting length (15-480).
        timezone: IANA timezone for naive datetimes.
        max_suggestions: number of slots to return (1-20, default 5).
        working_hours_start: local day start HH:MM (default 09:00).
        working_hours_end: local day end HH:MM (default 18:00).
        working_days: e.g. monday,tuesday,... (default Mon-Fri).
        buffer_minutes: padding around existing busy blocks.
    """
    try:
        (
            suggestions,
            partial,
            unresolved,
            backend,
            _window_start,
            _window_end,
            timezone_name,
            duration,
        ) = router.suggest_meeting_times(
            attendees,
            date_from,
            date_to,
            duration_minutes=duration_minutes,
            timezone=timezone or None,
            max_suggestions=max_suggestions,
            working_hours_start=working_hours_start,
            working_hours_end=working_hours_end,
            working_days=working_days,
            buffer_minutes=buffer_minutes,
        )
    except SchedulingError as exc:
        return {"error": True, "code": exc.code, "message": str(exc)}
    return {
        "backend": backend,
        "timezone": timezone_name,
        "duration_minutes": duration,
        "suggestions": [slot.to_dict() for slot in suggestions],
        "partial": partial,
        "unresolved_attendees": unresolved,
    }


def exchange_prepare_delete_event(
    event_id: str,
    delete_series: bool = False,
) -> dict:
    """Step 1/2: preview a calendar deletion and obtain a confirmation_id.

    DANGEROUS workflow guard: do NOT call `exchange_delete_event` until the
    user has read the preview and replied in chat with the exact phrase
    returned in `required_phrase` (default: «ДА, УДАЛИТЬ»).

    For recurring events: pass occurrence ``event_id`` to remove one instance.
    Pass ``delete_series=true`` with the series master id to remove all future
    occurrences.
    """
    try:
        pending, backend = router.prepare_delete_calendar_event(
            event_id,
            delete_series=delete_series,
        )
    except CalendarUpdateError as exc:
        return {"error": True, "code": exc.code, "message": str(exc)}
    scope = "entire series" if pending.get("delete_series") else "this occurrence"
    return {
        "backend": backend,
        "status": "awaiting_confirmation",
        "confirmation_id": pending["confirmation_id"],
        "required_phrase": pending["required_phrase"],
        "expires_at": pending["expires_at"],
        "delete_series": pending.get("delete_series", False),
        "recurrence_role": pending.get("recurrence_role", "single"),
        "event": {
            "id": pending["event_id"],
            "subject": pending["subject"],
            "start": pending["start"],
            "end": pending["end"],
        },
        "instructions": (
            "Show the user the event summary and deletion scope "
            f"({scope}). Only after they type the exact phrase "
            f"{pending['required_phrase']!r} in the chat, call "
            "exchange_delete_event with the same confirmation_id, event_id, "
            "delete_series, and user_confirmation equal to that phrase."
        ),
    }


def exchange_delete_event(
    event_id: str,
    confirmation_id: str,
    user_confirmation: str,
    delete_series: bool = False,
) -> dict:
    """Step 2/2: delete a calendar event after explicit user confirmation.

    Requires a fresh `confirmation_id` from `exchange_prepare_delete_event`
    (valid ~10 minutes). `user_confirmation` must match `required_phrase`
    exactly — the phrase the user typed in chat, e.g. «ДА, УДАЛИТЬ».
    ``delete_series`` must match the value used in prepare.
    """
    try:
        backend = router.delete_calendar_event(
            event_id,
            confirmation_id,
            user_confirmation,
            delete_series=delete_series,
        )
    except CalendarUpdateError as exc:
        return {"error": True, "code": exc.code, "message": str(exc)}
    return {
        "backend": backend,
        "status": "deleted",
        "event_id": event_id,
    }


def exchange_get_event(
    event_id: str,
    include_body: bool = True,
) -> dict:
    """Fetch one calendar event with full attendee lists and meeting metadata.

    Args:
        event_id: calendar item id from `exchange_get_calendar`.
        include_body: include event body text (default True).
    """
    try:
        event, backend = router.get_calendar_event(
            event_id, include_body=include_body,
        )
    except CalendarUpdateError as exc:
        return {"error": True, "code": exc.code, "message": str(exc)}
    return {
        "backend": backend,
        "event": event.to_dict(),
    }


def exchange_forward_event(
    event_id: str,
    to: list[str],
    body: str = "",
    body_is_html: bool = False,
    dry_run: bool = False,
    recurrence_scope: str = "single_occurrence",
) -> dict:
    """Forward a calendar meeting invitation to new recipients.

    Use this instead of `exchange_forward_email` for calendar items.
    Recipients receive a proper meeting request (Accept / Tentative / Decline).

    Args:
        event_id: calendar item id from `exchange_get_calendar`.
        to: recipient SMTP addresses.
        body: optional note added to the forwarded invitation.
        body_is_html: treat body as HTML when non-empty.
        dry_run: preview only, do not send.
        recurrence_scope: `single_occurrence` (default) or `series`.
    """
    try:
        result, backend = router.forward_calendar_event(
            event_id,
            to,
            body=body,
            body_is_html=body_is_html,
            dry_run=dry_run,
            recurrence_scope=recurrence_scope,
        )
    except CalendarUpdateError as exc:
        return {"error": True, "code": exc.code, "message": str(exc)}
    return {"backend": backend, **result}


def exchange_update_event_attendees(
    event_id: str,
    add_required: Optional[list[str]] = None,
    add_optional: Optional[list[str]] = None,
    remove: Optional[list[str]] = None,
    send_meeting_invitations: str = "to_changed",
    comment: str = "",
    dry_run: bool = False,
    recurrence_scope: str = "single_occurrence",
) -> dict:
    """Add or remove attendees on an existing meeting and send meeting updates.

    Only the organizer can change attendees. Default: notify changed attendees only.

    Args:
        event_id: calendar item id.
        add_required: emails to add as required attendees.
        add_optional: emails to add as optional attendees.
        remove: emails to remove from required or optional lists.
        send_meeting_invitations: `to_changed` (default), `to_all`, or `save_only`.
        comment: reserved for future use.
        dry_run: preview changes without saving.
        recurrence_scope: `single_occurrence` or `series`.
    """
    try:
        result, backend = router.update_event_attendees(
            event_id,
            add_required=add_required,
            add_optional=add_optional,
            remove=remove,
            send_meeting_invitations=send_meeting_invitations,
            comment=comment,
            dry_run=dry_run,
            recurrence_scope=recurrence_scope,
        )
    except CalendarUpdateError as exc:
        return {"error": True, "code": exc.code, "message": str(exc)}
    return {"backend": backend, **result}


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
    exchange_get_event,
    exchange_create_event,
    exchange_update_event,
    exchange_forward_event,
    exchange_update_event_attendees,
    exchange_prepare_delete_event,
    exchange_delete_event,
    exchange_get_availability,
    exchange_suggest_meeting_times,
    exchange_respond_to_event,
]
