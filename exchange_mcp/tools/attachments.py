"""Attachment tools — stub in v0.1."""
from __future__ import annotations


def exchange_get_attachment(item_id: str, attachment_id: str) -> dict:
    """Download an attachment by ID (NOT IMPLEMENTED in v0.1)."""
    return {"error": "exchange_get_attachment not implemented in v0.1",
            "item_id": item_id, "attachment_id": attachment_id}


TOOLS = [exchange_get_attachment]
