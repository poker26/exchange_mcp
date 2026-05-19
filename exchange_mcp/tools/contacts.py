"""Contact tools."""
from __future__ import annotations

from typing import Optional

from ..clients import router


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


TOOLS = [exchange_get_contacts]
