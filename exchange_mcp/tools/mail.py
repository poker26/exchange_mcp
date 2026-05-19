"""Mail tools."""
from __future__ import annotations

from typing import Optional

from ..backends.base import BackendError
from ..clients import router


def _inbox_id_or_raise() -> str:
    return router.ews.inbox_folder_id()


def exchange_get_new_emails(
    folder_id: Optional[str] = None,
    max_items: int = 50,
    include_body: bool = True,
) -> dict:
    """Return new emails since the last call (incremental, per-folder).

    Uses a shared cursor + Message-ID LRU under the hood (EWS).

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

    items, backend = router.get_emails_since(
        fid, since, limit=max_items, include_body=include_body,
    )
    return {
        "backend": backend,
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
    """Send an email via EWS.

    Args:
        to: list of recipient addresses.
        subject: subject line.
        body: message body (plain text unless body_is_html=True).
        cc: optional CC list.
        body_is_html: treat body as HTML.
    """
    backend = router.send_email(
        to=to, subject=subject, body=body, cc=cc, body_is_html=body_is_html,
    )
    return {"backend": backend, "status": "sent"}


def exchange_get_email(item_id: str) -> dict:
    """Fetch a single email by item id (from list/search results)."""
    mail_item, backend = router.get_email(item_id)
    return {
        "backend": backend,
        "email": mail_item.to_dict(),
    }


def exchange_mark_email_read(item_id: str, is_read: bool = True) -> dict:
    """Mark an email read or unread by item id."""
    backend = router.mark_email_read(item_id, is_read)
    return {
        "backend": backend,
        "item_id": item_id,
        "is_read": is_read,
        "status": "updated",
    }


def exchange_delete_email(item_id: str) -> dict:
    """Move an email to Deleted Items (trash)."""
    backend = router.delete_email(item_id)
    return {"backend": backend, "item_id": item_id, "status": "deleted"}


def exchange_move_email(item_id: str, target_folder_id: str) -> dict:
    """Move an email to another folder (use id from `exchange_list_folders`)."""
    backend = router.move_email(item_id, target_folder_id)
    return {
        "backend": backend,
        "item_id": item_id,
        "target_folder_id": target_folder_id,
        "status": "moved",
    }


def exchange_reply_email(
    item_id: str,
    body: str,
    reply_all: bool = False,
    body_is_html: bool = False,
) -> dict:
    """Reply (or reply-all) to an email by item id."""
    backend = router.reply_email(
        item_id, body, reply_all=reply_all, body_is_html=body_is_html,
    )
    return {
        "backend": backend,
        "item_id": item_id,
        "reply_all": reply_all,
        "status": "sent",
    }


def exchange_forward_email(
    item_id: str,
    to: list[str],
    body: str = "",
    cc: Optional[list[str]] = None,
    body_is_html: bool = False,
) -> dict:
    """Forward an email to new recipients."""
    backend = router.forward_email(
        item_id, to, body=body, cc=cc, body_is_html=body_is_html,
    )
    return {
        "backend": backend,
        "item_id": item_id,
        "to": to,
        "status": "sent",
    }


def exchange_search_emails(
    query: str,
    max_items: int = 20,
    folder_id: Optional[str] = None,
    search_body: bool = False,
) -> dict:
    """Search emails by subject/sender (and optionally body) in a folder.

    Defaults to Inbox; pass folder_id for Sent or other folders.
    """
    max_items = max(1, min(int(max_items), 100))
    items, backend = router.search_emails(
        query,
        limit=max_items,
        folder_id=folder_id,
        search_body=search_body,
    )
    return {
        "backend": backend,
        "query": query,
        "folder_id": folder_id,
        "search_body": search_body,
        "count": len(items),
        "emails": [mail_item.to_dict() for mail_item in items],
    }


TOOLS = [
    exchange_get_new_emails,
    exchange_get_emails,
    exchange_get_email,
    exchange_send_email,
    exchange_search_emails,
    exchange_mark_email_read,
    exchange_delete_email,
    exchange_move_email,
    exchange_reply_email,
    exchange_forward_email,
]
