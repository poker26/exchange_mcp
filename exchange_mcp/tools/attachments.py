"""Attachment tools."""
from __future__ import annotations

from ..clients import router


def exchange_list_attachments(item_id: str) -> dict:
    """List attachment metadata on an email (no file content)."""
    items, backend = router.list_attachments(item_id)
    return {
        "backend": backend,
        "item_id": item_id,
        "count": len(items),
        "attachments": [attachment.to_dict() for attachment in items],
    }


def exchange_get_attachment(item_id: str, attachment_id: str) -> dict:
    """Download an attachment by message item id and attachment id (EWS).

    Returns base64-encoded content (max 10 MB). Use ids from email list /
    attachment metadata on the message.
    """
    data, backend = router.get_attachment(item_id, attachment_id)
    result = data.to_dict()
    result["backend"] = backend
    return result


def exchange_stage_email_attachments(
    item_id: str,
    attachment_presign_ttl: int = 86400,
    include_inline: bool = False,
) -> dict:
    """Download all file attachments for an email, upload to MinIO, presign.

    Requires MinIO env vars on the server. Skips inline parts by default.
    """
    ttl = max(60, min(int(attachment_presign_ttl), 604800))
    staged, backend = router.stage_email_attachments(
        item_id,
        expires_seconds=ttl,
        include_inline=include_inline,
    )
    return {
        "backend": backend,
        "item_id": item_id,
        "count": len(staged),
        "attachments": staged,
    }


TOOLS = [exchange_list_attachments, exchange_get_attachment, exchange_stage_email_attachments]
