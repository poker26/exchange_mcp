"""Attachment tools."""
from __future__ import annotations

from ..clients import router


def exchange_get_attachment(item_id: str, attachment_id: str) -> dict:
    """Download an attachment by message item id and attachment id (EWS).

    Returns base64-encoded content (max 10 MB). Use ids from email list /
    attachment metadata on the message.
    """
    data, backend = router.get_attachment(item_id, attachment_id)
    result = data.to_dict()
    result["backend"] = backend
    return result


TOOLS = [exchange_get_attachment]
