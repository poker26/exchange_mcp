"""Routes each call to the preferred backend, falling back on failure.

State flow for `get_new_mail`:
    1. Pick preferred backend by the most recent healthcheck result.
    2. Compute query window: `since = cursor - SAFETY_MARGIN` (or None
       if no cursor yet). Safety margin bridges clock drift and ensures
       we never miss mail on channel switches.
    3. Fetch items from backend.
    4. Filter against Message-ID LRU → new items only.
    5. Advance cursor to max(received) of returned items.
    6. Record new Message-IDs in LRU.

If the preferred backend raises BackendError or times out, we flip it
to unhealthy, try the other one, and log the switch.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from .backends.base import BackendError, FolderInfo, MailBackend, MailItem
from .backends.ews import EWSBackend
from .backends.eas import EASBackend
from .config import settings
from .state import SharedState

logger = logging.getLogger(__name__)


# Overlap applied to the cursor on every query — avoids edge-case misses
# from clock skew and eventual-consistency windows on the Exchange side.
_SAFETY_MARGIN = timedelta(minutes=5)

# How long a healthcheck result stays fresh.
_HEALTH_TTL = 60.0  # seconds


class MailRouter:
    def __init__(self) -> None:
        self.ews = EWSBackend()
        self.eas = EASBackend()
        self.state = SharedState(
            path=os.path.join(settings.state_dir, "router_state.json"),
        )
        self._health: dict[str, tuple[bool, float]] = {}  # name -> (ok, ts)
        self._health_lock = threading.RLock()

    # --- health ------------------------------------------------------
    def _healthy(self, backend: MailBackend) -> bool:
        with self._health_lock:
            entry = self._health.get(backend.name)
            if entry is not None:
                ok, ts = entry
                if time.monotonic() - ts < _HEALTH_TTL:
                    return ok
        ok = False
        try:
            ok = backend.healthcheck()
        except Exception as e:
            logger.warning("%s healthcheck raised: %s", backend.name, e)
        with self._health_lock:
            self._health[backend.name] = (ok, time.monotonic())
        return ok

    def _mark_unhealthy(self, backend: MailBackend) -> None:
        with self._health_lock:
            self._health[backend.name] = (False, time.monotonic())

    def health_snapshot(self) -> dict:
        snapshot: dict[str, dict] = {}
        for b in (self.ews, self.eas):
            ok = self._healthy(b)
            last_err = getattr(b, "last_error", lambda: None)()
            snapshot[b.name] = {"ok": ok, "last_error": last_err}
        snapshot["preferred"] = self._preferred_name()
        return snapshot

    # --- routing -----------------------------------------------------
    def _preferred_name(self) -> str:
        return "ews" if settings.preferred_backend.lower() == "ews" else "eas"

    def _backend_order(self) -> list[MailBackend]:
        if self._preferred_name() == "ews":
            return [self.ews, self.eas]
        return [self.eas, self.ews]

    def _try(self, op_name: str, fn):
        """Run `fn(backend)` on the preferred backend, fall back on failure."""
        order = self._backend_order()
        last_exc: Optional[Exception] = None
        for i, backend in enumerate(order):
            if not self._healthy(backend) and i < len(order) - 1:
                logger.info("%s: skipping %s (unhealthy)", op_name, backend.name)
                continue
            try:
                return fn(backend), backend
            except BackendError as e:
                last_exc = e
                logger.warning("%s on %s: %s — falling back", op_name, backend.name, e)
                self._mark_unhealthy(backend)
                continue
            except Exception as e:
                last_exc = e
                logger.warning(
                    "%s on %s raised %s — falling back",
                    op_name, backend.name, type(e).__name__,
                )
                self._mark_unhealthy(backend)
                continue
        raise BackendError(f"{op_name}: all backends failed ({last_exc})")

    # --- operations --------------------------------------------------
    def list_folders(self) -> tuple[list[FolderInfo], str]:
        result, backend = self._try("list_folders", lambda b: b.list_folders())
        return result, backend.name

    def get_new_mail(
        self,
        folder_id: str,
        limit: int = 50,
        include_body: bool = True,
    ) -> tuple[list[MailItem], str, bool]:
        """Return (new_items, backend_used, is_initial).

        is_initial=True means no prior cursor existed; the caller may
        want to treat the first response specially (e.g. don't spam
        the user with a week of backlog).
        """
        cursor = self.state.get_cursor(folder_id)
        is_initial = cursor is None
        since = (cursor - _SAFETY_MARGIN) if cursor else None

        def _op(b: MailBackend) -> list[MailItem]:
            return b.get_items_since(folder_id, since, limit=limit,
                                     include_body=include_body)

        items, backend = self._try("get_new_mail", _op)

        new_items: list[MailItem] = []
        new_mids: list[str] = []
        max_received: Optional[datetime] = None
        for m in items:
            if m.message_id and self.state.contains(folder_id, m.message_id):
                continue
            new_items.append(m)
            if m.message_id:
                new_mids.append(m.message_id)
            if m.received and (max_received is None or m.received > max_received):
                max_received = m.received

        if max_received is not None:
            self.state.set_cursor(folder_id, max_received)
        if new_mids:
            self.state.mark_seen(folder_id, new_mids)

        return new_items, backend.name, is_initial
