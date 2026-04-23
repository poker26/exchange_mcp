"""Contact tools — stub in v0.1."""
from __future__ import annotations

from typing import Optional


def exchange_get_contacts(
    folder_id: Optional[str] = None,
    max_items: int = 50,
) -> dict:
    """Fetch contacts from the address book (NOT IMPLEMENTED in v0.1)."""
    return {"error": "exchange_get_contacts not implemented in v0.1",
            "folder_id": folder_id, "max_items": max_items}


TOOLS = [exchange_get_contacts]
