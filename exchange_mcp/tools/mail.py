"""Mail tools."""
from __future__ import annotations

from typing import Optional

from ..backends.base import BackendError
from ..clients import router


def _inbox_id_or_raise() -> str:
    folders, _ = router.list_folders()
    for f in folders:
        if f.type == 2:  # Inbox
            return f.id
    raise BackendError("Inbox folder not found")


def exchange_get_new_emails(
    folder_id: Optional[str] = None,
    max_items: int = 50,
    include_body: bool = True,
) -> dict:
    """Return new emails since the last call (incremental, per-folder).

    Uses a shared cursor + Message-ID LRU under the hood, so this is
    safe across EWS ↔ EAS failovers: you won't get duplicates when
    the channel switches, and you won't miss mail that arrived during
    a brief outage.

    Args:
        folder_id: folder id from `exchange_list_folders`; defaults to Inbox.
        max_items: max emails to return (1-200).
        include_body: include text body (default True).
    """
    max_items = max(1, min(int(max_items), 200))
    fid = folder_id or _inbox_id_or_raise()
    items, backend, is_initial = router.get_new_mail(
        fid, limit=max_items, include_body=include_body,
    )
    return {
        "backend": backend,
        "folder_id": fid,
        "is_initial": is_initial,
        "count": len(items),
        "emails": [m.to_dict() for m in items],
    }


def exchange_get_emails(
    folder_id: Optional[str] = None,
    max_items: int = 50,
    include_body: bool = True,
) -> dict:
    """List the most recent emails in a folder (non-incremental).

    v0.1: backed by the same get_items_since path with a one-month
    window; no cursor is read or written. Use `exchange_get_new_emails`
    for incremental consumption.
    """
    max_items = max(1, min(int(max_items), 200))
    fid = folder_id or _inbox_id_or_raise()
    # Temporary: reuse the router with since=None -> backend default window.
    # Intentionally bypasses the shared cursor so repeated calls keep
    # returning the same batch.
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=31)

    # We call the backends directly to avoid mutating the shared cursor.
    def _op(b):
        return b.get_items_since(fid, since, limit=max_items, include_body=include_body)

    items, backend = router._try("get_emails", _op)  # noqa: SLF001
    return {
        "backend": backend.name,
        "folder_id": fid,
        "count": len(items),
        "emails": [m.to_dict() for m in items],
    }


def exchange_send_email(
    to: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    body_is_html: bool = False,
) -> dict:
    """Send an email via the preferred channel (EWS only in v0.1).

    Args:
        to: list of recipient addresses.
        subject: subject line.
        body: message body (plain text unless body_is_html=True).
        cc: optional CC list.
        body_is_html: treat body as HTML.
    """
    def _op(b):
        b.send_email(to=to, subject=subject, body=body, cc=cc,
                     body_is_html=body_is_html)
        return None

    _, backend = router._try("send_email", _op)  # noqa: SLF001
    return {"backend": backend.name, "status": "sent"}


def exchange_search_emails(query: str, max_items: int = 20) -> dict:
    """Search emails by subject/sender/content (NOT IMPLEMENTED in v0.1)."""
    return {"error": "exchange_search_emails not implemented in v0.1",
            "query": query, "max_items": max_items}


TOOLS = [
    exchange_get_new_emails,
    exchange_get_emails,
    exchange_send_email,
    exchange_search_emails,
]
