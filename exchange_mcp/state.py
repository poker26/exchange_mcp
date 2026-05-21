"""Persistent state for EWS incremental mail (cursor + dedup).

Contract:
    per-folder cursor: last_seen_received_datetime (UTC, ISO-8601)
    per-folder dedup:  bounded set of Message-IDs (RFC 5322)

Persistence is atomic: a crash mid-write leaves the previous file intact.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

_DEFAULT_LRU_SIZE = 2000


class _FolderState:
    __slots__ = ("cursor", "seen", "calendar_events")

    def __init__(
        self,
        cursor: Optional[str] = None,
        seen: Optional[Iterable[str]] = None,
        max_seen: int = _DEFAULT_LRU_SIZE,
        calendar_events: Optional[dict[str, dict]] = None,
    ):
        # cursor is kept as an ISO-8601 string so it round-trips JSON cleanly.
        self.cursor: Optional[str] = cursor
        self.seen: OrderedDict[str, None] = OrderedDict()
        if seen:
            for mid in list(seen)[-max_seen:]:
                self.seen[mid] = None
        self.calendar_events: dict[str, dict] = dict(calendar_events or {})

    def to_dict(self) -> dict:
        payload = {"cursor": self.cursor, "seen": list(self.seen.keys())}
        if self.calendar_events:
            payload["calendar_events"] = self.calendar_events
        return payload


class SharedState:
    """In-memory shared state with atomic JSON persistence.

    Not coroutine-aware — callers should run it in a thread pool or
    accept that writes briefly block the event loop. For MCP's
    request-per-call pattern that's fine; switch to an asyncio-aware
    lock if streaming notifications start hammering it.
    """

    def __init__(self, path: str, max_seen: int = _DEFAULT_LRU_SIZE):
        self.path = path
        self.max_seen = max_seen
        self._folders: dict[str, _FolderState] = {}
        self._lock = threading.RLock()
        self._load()

    # --- persistence --------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self.path, "r") as f:
                raw = json.load(f)
        except FileNotFoundError:
            logger.info("No state file at %s; starting fresh", self.path)
            return
        except (OSError, json.JSONDecodeError) as e:
            logger.error("State file %s unreadable (%s); starting fresh", self.path, e)
            return

        for fid, blob in raw.get("folders", {}).items():
            self._folders[fid] = _FolderState(
                cursor=blob.get("cursor"),
                seen=blob.get("seen") or [],
                max_seen=self.max_seen,
                calendar_events=blob.get("calendar_events") or {},
            )
        logger.info("Loaded state for %d folders from %s",
                    len(self._folders), self.path)

    def _save_locked(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        payload = {
            "folders": {fid: fs.to_dict() for fid, fs in self._folders.items()},
        }
        try:
            with open(tmp, "w") as f:
                json.dump(payload, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except OSError as e:
            logger.error("Failed to save state to %s: %s", self.path, e)
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # --- cursor -------------------------------------------------------
    def get_cursor(self, folder_id: str) -> Optional[datetime]:
        """Return the cursor as an aware UTC datetime, or None."""
        with self._lock:
            fs = self._folders.get(folder_id)
            if not fs or not fs.cursor:
                return None
        try:
            # fromisoformat handles both naive and aware strings in 3.11+
            dt = datetime.fromisoformat(fs.cursor)
        except ValueError:
            logger.warning("Bad cursor %r for folder %s; ignoring", fs.cursor, folder_id)
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def set_cursor(self, folder_id: str, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        with self._lock:
            fs = self._folders.setdefault(folder_id, _FolderState(max_seen=self.max_seen))
            fs.cursor = dt.astimezone(timezone.utc).isoformat()
            self._save_locked()

    # --- dedup --------------------------------------------------------
    def contains(self, folder_id: str, message_id: str) -> bool:
        if not message_id:
            return False
        with self._lock:
            fs = self._folders.get(folder_id)
            return bool(fs and message_id in fs.seen)

    def mark_seen(self, folder_id: str, message_ids: Iterable[str]) -> None:
        changed = False
        with self._lock:
            fs = self._folders.setdefault(folder_id, _FolderState(max_seen=self.max_seen))
            for mid in message_ids:
                if not mid:
                    continue
                if mid in fs.seen:
                    fs.seen.move_to_end(mid)
                else:
                    fs.seen[mid] = None
                    changed = True
                while len(fs.seen) > self.max_seen:
                    fs.seen.popitem(last=False)
            if changed:
                self._save_locked()

    def get_calendar_events(self, folder_id: str) -> dict[str, dict]:
        with self._lock:
            folder_state = self._folders.get(folder_id)
            if not folder_state:
                return {}
            return dict(folder_state.calendar_events)

    def set_calendar_event(
        self,
        folder_id: str,
        uid: str,
        event_state: dict,
    ) -> None:
        if not uid:
            return
        with self._lock:
            folder_state = self._folders.setdefault(
                folder_id, _FolderState(max_seen=self.max_seen),
            )
            folder_state.calendar_events[uid] = dict(event_state)
            self._save_locked()

    def remove_calendar_event(self, folder_id: str, uid: str) -> None:
        if not uid:
            return
        with self._lock:
            folder_state = self._folders.get(folder_id)
            if not folder_state or uid not in folder_state.calendar_events:
                return
            del folder_state.calendar_events[uid]
            self._save_locked()

    def snapshot(self) -> dict:
        """Return a JSON-serializable snapshot (for /health and debugging)."""
        with self._lock:
            return {
                fid: {
                    "cursor": fs.cursor,
                    "seen_count": len(fs.seen),
                    "calendar_events_count": len(fs.calendar_events),
                }
                for fid, fs in self._folders.items()
            }
