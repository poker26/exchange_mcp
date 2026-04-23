"""Folder enumeration."""
from __future__ import annotations

from ..clients import router


def exchange_list_folders() -> dict:
    """List mailbox folders (Inbox, Sent, Calendar, etc.) with IDs and types.

    Returns a JSON-serializable dict with a "folders" key. Each folder
    has {id, name, type, parent}. `type` follows the EAS FolderSync
    numeric codes (2=Inbox, 5=Sent, 8=Calendar, 9=Contacts, etc.), so
    downstream code can pick folders by semantic role without knowing
    which channel served the request.
    """
    folders, backend = router.list_folders()
    return {
        "backend": backend,
        "folders": [
            {"id": f.id, "name": f.name, "type": f.type, "parent": f.parent}
            for f in folders
        ],
        "count": len(folders),
    }


TOOLS = [exchange_list_folders]
