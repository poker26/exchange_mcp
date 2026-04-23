"""Calendar tools — stubs in v0.1."""
from __future__ import annotations

from typing import Optional


def exchange_get_calendar(
    folder_id: Optional[str] = None,
    date_from: str = "",
    date_to: str = "",
) -> dict:
    """Fetch calendar events in a date range (NOT IMPLEMENTED in v0.1)."""
    return {"error": "exchange_get_calendar not implemented in v0.1",
            "folder_id": folder_id, "date_from": date_from, "date_to": date_to}


def exchange_get_new_events(
    folder_id: Optional[str] = None,
    max_items: int = 50,
) -> dict:
    """Return new/changed calendar events since last call (NOT IMPLEMENTED in v0.1)."""
    return {"error": "exchange_get_new_events not implemented in v0.1",
            "folder_id": folder_id, "max_items": max_items}


def exchange_create_event(
    subject: str,
    start: str,
    end: str,
    location: str = "",
    body: str = "",
    attendees: Optional[list[str]] = None,
) -> dict:
    """Create a calendar event (NOT IMPLEMENTED in v0.1)."""
    return {"error": "exchange_create_event not implemented in v0.1",
            "subject": subject}


TOOLS = [
    exchange_get_calendar,
    exchange_get_new_events,
    exchange_create_event,
]
