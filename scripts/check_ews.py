"""Quick EWS connectivity check. Run from project root with .env present.

    python scripts/check_ews.py
"""
from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from exchange_mcp.backends.ews import EWSBackend
from exchange_mcp.config import settings


def main() -> int:
    if settings.exchange_password in ("", "change-me"):
        print("ERROR: set EXCHANGE_PASSWORD in .env")
        return 1

    print(f"EWS URL: {settings.ews_effective_url}")
    print(f"User:    {settings.exchange_user}")

    backend = EWSBackend()
    if not backend.healthcheck():
        print(f"FAIL: {backend.last_error()}")
        return 2

    inbox_id = backend.inbox_folder_id()
    folders = backend.list_folders()
    print("OK: EWS reachable")
    print(f"Inbox folder id: {inbox_id}")
    print(f"Folders: {len(folders)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
