"""Routes all mail operations to the EWS backend.

State flow for `get_new_mail`:
    1. Compute query window: `since = cursor - SAFETY_MARGIN` (or None
       if no cursor yet). Safety margin bridges clock drift.
    2. Fetch items from EWS.
    3. Filter against Message-ID LRU → new items only.
    4. Advance cursor to max(received) of returned items.
    5. Record new Message-IDs in LRU.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional, TypeVar

from .backends.base import BackendError, FolderInfo, MailItem
from .backends.ews import EWSBackend
from .config import settings
from .state import SharedState

logger = logging.getLogger(__name__)

_SAFETY_MARGIN = timedelta(minutes=5)
_HEALTH_TTL = 60.0

ReturnType = TypeVar("ReturnType")


class MailRouter:
    def __init__(self) -> None:
        self.ews = EWSBackend()
        self.state = SharedState(
            path=os.path.join(settings.state_dir, "router_state.json"),
        )
        self._ews_healthy: Optional[tuple[bool, float]] = None
        self._health_lock = threading.RLock()

    def _healthy(self) -> bool:
        with self._health_lock:
            if self._ews_healthy is not None:
                ok, checked_at = self._ews_healthy
                if time.monotonic() - checked_at < _HEALTH_TTL:
                    return ok
        ok = False
        try:
            ok = self.ews.healthcheck()
        except Exception as exc:
            logger.warning("EWS healthcheck raised: %s", exc)
        with self._health_lock:
            self._ews_healthy = (ok, time.monotonic())
        return ok

    def _mark_unhealthy(self) -> None:
        with self._health_lock:
            self._ews_healthy = (False, time.monotonic())

    def health_snapshot(self) -> dict:
        ok = self._healthy()
        return {
            "backend": "ews",
            "ews": {
                "ok": ok,
                "last_error": self.ews.last_error(),
            },
        }

    def _execute(
        self,
        operation_name: str,
        operation: Callable[[EWSBackend], ReturnType],
    ) -> tuple[ReturnType, EWSBackend]:
        try:
            return operation(self.ews), self.ews
        except BackendError:
            self._mark_unhealthy()
            raise
        except Exception as exc:
            self._mark_unhealthy()
            raise BackendError(f"{operation_name}: {exc}") from exc

    def list_folders(self) -> tuple[list[FolderInfo], str]:
        result, _backend = self._execute("list_folders", lambda ews: ews.list_folders())
        return result, "ews"

    def get_new_mail(
        self,
        folder_id: str,
        limit: int = 50,
        include_body: bool = True,
    ) -> tuple[list[MailItem], str, bool]:
        cursor = self.state.get_cursor(folder_id)
        is_initial = cursor is None
        since = (cursor - _SAFETY_MARGIN) if cursor else None

        def _fetch(ews: EWSBackend) -> list[MailItem]:
            return ews.get_items_since(
                folder_id, since, limit=limit, include_body=include_body,
            )

        items, _backend = self._execute("get_new_mail", _fetch)

        new_items: list[MailItem] = []
        new_message_ids: list[str] = []
        max_received: Optional[datetime] = None
        for mail_item in items:
            if mail_item.message_id and self.state.contains(
                folder_id, mail_item.message_id,
            ):
                continue
            new_items.append(mail_item)
            if mail_item.message_id:
                new_message_ids.append(mail_item.message_id)
            if mail_item.received and (
                max_received is None or mail_item.received > max_received
            ):
                max_received = mail_item.received

        if max_received is not None:
            self.state.set_cursor(folder_id, max_received)
        if new_message_ids:
            self.state.mark_seen(folder_id, new_message_ids)

        return new_items, "ews", is_initial

    def get_emails_since(
        self,
        folder_id: str,
        since: datetime,
        limit: int = 50,
        include_body: bool = True,
    ) -> tuple[list[MailItem], str]:
        def _fetch(ews: EWSBackend) -> list[MailItem]:
            return ews.get_items_since(
                folder_id, since, limit=limit, include_body=include_body,
            )

        items, _backend = self._execute("get_emails", _fetch)
        return items, "ews"

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: Optional[list[str]] = None,
        body_is_html: bool = False,
    ) -> str:
        def _send(ews: EWSBackend) -> None:
            ews.send_email(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                body_is_html=body_is_html,
            )

        self._execute("send_email", _send)
        return "ews"
