"""Contact tools."""
from __future__ import annotations

from typing import Optional

from ..clients import router
from ..scheduling_util import SchedulingError


def exchange_get_contacts(
    folder_id: Optional[str] = None,
    max_items: int = 50,
) -> dict:
    """Fetch contacts from the address book (EWS)."""
    max_items = max(1, min(int(max_items), 200))
    items, backend = router.get_contacts(folder_id, limit=max_items)
    return {
        "backend": backend,
        "folder_id": folder_id,
        "count": len(items),
        "contacts": [contact.to_dict() for contact in items],
    }


def exchange_search_contacts(query: str, max_items: int = 20) -> dict:
    """Search the global address list and contacts folder by name or email.

    Use this to resolve human names to SMTP addresses before scheduling.
    Returns all known SMTP addresses in ``emails``; ``email`` is the
    preferred one (organizer domain when available).

    Args:
        query: substring of display name or email (at least 2 characters).
        max_items: max results (1-50, default 20).
    """
    search_text = (query or "").strip()
    if len(search_text) < 2:
        return {
            "error": True,
            "code": "QUERY_TOO_SHORT",
            "message": "query must be at least 2 characters",
        }
    max_items = max(1, min(int(max_items), 50))
    try:
        items, backend = router.search_contacts(search_text, limit=max_items)
    except SchedulingError as exc:
        return {"error": True, "code": exc.code, "message": str(exc)}
    return {
        "backend": backend,
        "query": search_text,
        "count": len(items),
        "contacts": [contact.to_dict() for contact in items],
    }


TOOLS = [exchange_get_contacts, exchange_search_contacts]
