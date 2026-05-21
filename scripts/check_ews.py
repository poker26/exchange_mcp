"""Quick EWS connectivity check. Run from project root with .env present.

    python scripts/check_ews.py
    python scripts/check_ews.py --search "test"
    python scripts/check_ews.py --availability colleague@company.ru --from 2026-05-19 --to 2026-05-20
    python scripts/check_ews.py --suggest colleague@company.ru --from 2026-05-19 --to 2026-05-23 --duration 30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from exchange_mcp.backends.ews import EWSBackend
from exchange_mcp.config import settings
from exchange_mcp.router import MailRouter


def main() -> int:
    parser = argparse.ArgumentParser(description="EWS smoke checks")
    parser.add_argument("--search", metavar="QUERY", help="exchange_search_contacts")
    parser.add_argument(
        "--availability",
        metavar="EMAIL",
        action="append",
        dest="availability_emails",
        help="attendee email for free/busy (repeatable)",
    )
    parser.add_argument("--from", dest="date_from", metavar="ISO", help="window start")
    parser.add_argument("--to", dest="date_to", metavar="ISO", help="window end")
    parser.add_argument(
        "--suggest",
        metavar="EMAIL",
        action="append",
        dest="suggest_emails",
        help="attendee email for slot suggestions (repeatable)",
    )
    parser.add_argument("--duration", type=int, default=30, help="meeting minutes")
    args = parser.parse_args()

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

    router = MailRouter()

    if args.search:
        items, _ = router.search_contacts(args.search, limit=5)
        print(f"Search {args.search!r}: {len(items)} hit(s)")
        for contact in items:
            print(f"  - {contact.display_name} <{contact.email}>")

    if args.availability_emails:
        if not args.date_from or not args.date_to:
            print("ERROR: --from and --to required with --availability")
            return 3
        rows, errors, _, start, end, tz = router.get_availability(
            args.availability_emails,
            args.date_from,
            args.date_to,
        )
        print(f"Availability {start.isoformat()} .. {end.isoformat()} ({tz})")
        for row in rows:
            print(f"  {row.email} [{row.calendar_status}] busy={len(row.busy)}")
        for err in errors:
            print(f"  error: {err}")

    if args.suggest_emails:
        if not args.date_from or not args.date_to:
            print("ERROR: --from and --to required with --suggest")
            return 4
        suggestions, partial, unresolved, _, _, _, tz, duration = router.suggest_meeting_times(
            args.suggest_emails,
            args.date_from,
            args.date_to,
            duration_minutes=args.duration,
        )
        print(
            f"Suggest {duration} min, partial={partial}, "
            f"unresolved={unresolved} ({tz})",
        )
        for slot in suggestions:
            print(
                f"  - {slot.start.isoformat()} .. {slot.end.isoformat()} "
                f"score={slot.score} all_free={slot.all_attendees_free}",
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
