"""Helpers for calendar meeting forward and attendee management."""
from __future__ import annotations

from exchange_mcp.config import settings
from exchange_mcp.backends.base import CalendarUpdateError
from exchange_mcp.calendar_recurrence import (
    RECURRENCE_ROLE_SERIES_MASTER,
    classify_calendar_recurrence_role,
    extract_recurring_master_id,
    is_recurring_instance_role,
    is_series_master_role,
)
from exchange_mcp.scheduling_util import is_valid_email_address, normalize_email_address

RECURRENCE_SCOPE_SINGLE = "single_occurrence"
RECURRENCE_SCOPE_SERIES = "series"


def normalize_recurrence_scope(scope: str) -> str:
    normalized = (scope or RECURRENCE_SCOPE_SINGLE).strip().lower()
    if normalized in (RECURRENCE_SCOPE_SINGLE, "single", "occurrence"):
        return RECURRENCE_SCOPE_SINGLE
    if normalized in (RECURRENCE_SCOPE_SERIES, "series", "master"):
        return RECURRENCE_SCOPE_SERIES
    raise CalendarUpdateError(
        "INVALID_RECURRENCE_SCOPE",
        "recurrence_scope must be single_occurrence or series",
    )


def normalize_smtp_address(value: str) -> str:
    text = (value or "").strip()
    if text.upper().startswith("SMTP:"):
        return text[5:].strip().lower()
    return text.lower()


def attendee_smtp_address(attendee) -> str:
    mailbox = getattr(attendee, "mailbox", None)
    raw = (
        getattr(attendee, "email_address", "")
        or getattr(mailbox, "email_address", "")
        or getattr(attendee, "name", "")
        or ""
    )
    return normalize_smtp_address(raw)


def attendee_display_name(attendee) -> str:
    return (
        getattr(attendee, "name", "")
        or getattr(getattr(attendee, "mailbox", None), "name", "")
        or attendee_smtp_address(attendee)
    )


def map_attendee_record(attendee) -> dict:
    response_raw = str(getattr(attendee, "response_type", "Unknown") or "Unknown")
    return {
        "name": attendee_display_name(attendee),
        "email": attendee_smtp_address(attendee),
        "response": response_raw.strip().lower(),
    }


def organizer_smtp_address(item) -> str:
    organizer = getattr(item, "organizer", None)
    if organizer is None:
        return ""
    return normalize_smtp_address(
        getattr(organizer, "email_address", "")
        or getattr(organizer, "name", "")
        or "",
    )


def is_mailbox_organizer(item) -> bool:
    mailbox_email = normalize_email_address((settings.exchange_email or "").strip())
    if not mailbox_email:
        return False
    organizer_email = organizer_smtp_address(item)
    if organizer_email and organizer_email == mailbox_email:
        return True
    my_response = str(getattr(item, "my_response_type", "") or "").strip().lower()
    return my_response == "organizer"


def assert_can_manage_attendees(item) -> None:
    if is_mailbox_organizer(item):
        return
    raise CalendarUpdateError(
        "NOT_ORGANIZER",
        "only the meeting organizer can add or remove attendees; "
        f"organizer is {organizer_smtp_address(item) or 'unknown'}",
    )


def assert_can_forward_calendar_item(item) -> None:
    if is_mailbox_organizer(item):
        return
    if bool(getattr(item, "is_meeting", False)):
        return
    raise CalendarUpdateError(
        "CAN_FORWARD_ONLY",
        "this calendar item cannot be forwarded as a meeting invitation",
    )


def resolve_calendar_item_for_scope(
    account,
    event_id: str,
    recurrence_scope: str,
    *,
    fetch_item_by_id,
):
    from exchangelib import CalendarItem as EwsCalendarItem  # type: ignore[import-not-found]

    scope = normalize_recurrence_scope(recurrence_scope)
    try:
        item = fetch_item_by_id(account, event_id)
    except Exception as exc:
        raise CalendarUpdateError(
            "EVENT_NOT_FOUND",
            f"event {event_id!r} not found: {exc}",
        ) from exc

    if not isinstance(item, EwsCalendarItem):
        raise CalendarUpdateError(
            "NOT_A_CALENDAR_ITEM",
            f"item {event_id!r} is not a calendar event",
        )

    role = classify_calendar_recurrence_role(item)
    if scope == RECURRENCE_SCOPE_SERIES:
        if is_recurring_instance_role(role):
            master_id = extract_recurring_master_id(item)
            if not master_id:
                raise CalendarUpdateError(
                    "RECURRENCE_SCOPE_REQUIRED",
                    "could not resolve series master for this occurrence",
                )
            item = fetch_item_by_id(account, master_id)
            if not isinstance(item, EwsCalendarItem):
                raise CalendarUpdateError(
                    "NOT_A_CALENDAR_ITEM",
                    "series master is not a calendar event",
                )
        return item

    if is_series_master_role(role) or role == RECURRENCE_ROLE_SERIES_MASTER:
        raise CalendarUpdateError(
            "RECURRENCE_SCOPE_REQUIRED",
            "event_id points to a recurring series master; use an occurrence id "
            "with recurrence_scope=single_occurrence, or recurrence_scope=series "
            "to update the entire series",
        )
    return item


def validate_recipient_list(recipients: list[str]) -> list[str]:
    if not recipients:
        raise CalendarUpdateError(
            "INVALID_ATTENDEE",
            "at least one recipient email is required",
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_address in recipients:
        address = normalize_smtp_address(raw_address)
        if not address or address in seen:
            continue
        if not is_valid_email_address(address):
            raise CalendarUpdateError(
                "INVALID_ATTENDEE",
                f"invalid recipient email: {raw_address!r}",
            )
        seen.add(address)
        normalized.append(address)
    if not normalized:
        raise CalendarUpdateError(
            "INVALID_ATTENDEE",
            "at least one valid recipient email is required",
        )
    return normalized


def merge_attendee_lists(
    existing_attendees,
    add_emails: list[str],
    remove_emails: list[str],
    *,
    create_attendee,
):
    remove_set = {normalize_smtp_address(email) for email in remove_emails}
    merged = []
    seen: set[str] = set()

    for attendee in existing_attendees or []:
        email = attendee_smtp_address(attendee)
        if not email or email in remove_set or email in seen:
            continue
        seen.add(email)
        merged.append(attendee)

    added: list[str] = []
    for raw_email in add_emails:
        email = normalize_smtp_address(raw_email)
        if not email or email in seen:
            continue
        if not is_valid_email_address(email):
            raise CalendarUpdateError(
                "INVALID_ATTENDEE",
                f"invalid attendee email: {raw_email!r}",
            )
        seen.add(email)
        merged.append(create_attendee(email))
        added.append(email)

    removed_present = [
        email for email in remove_set
        if any(
            attendee_smtp_address(attendee) == email
            for attendee in (existing_attendees or [])
        )
    ]
    return merged, added, removed_present
