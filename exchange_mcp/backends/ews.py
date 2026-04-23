"""EWS driver backed by exchangelib.

Initialization is lazy so the process can start even if EWS is
unreachable at boot (VPN down). healthcheck() is the canonical way to
decide whether to route traffic here.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import settings
from .base import BackendError, CalendarItem, FolderInfo, MailBackend, MailItem

logger = logging.getLogger(__name__)


# EAS folder type codes we mirror, so tools/ can pick Inbox/Calendar by number.
_EWS_FOLDER_TYPE = {
    "inbox": 2,
    "drafts": 3,
    "deleted": 4,
    "sent": 5,
    "outbox": 6,
    "tasks": 7,
    "calendar": 8,
    "contacts": 9,
    "journal": 11,
    "notes": 10,
}


class EWSBackend:
    name = "ews"

    def __init__(self) -> None:
        self._account = None
        self._account_err: Optional[str] = None
        self._init_lock = threading.Lock()

    # --- lazy init ---------------------------------------------------
    def _account_or_raise(self):
        if self._account is not None:
            return self._account
        with self._init_lock:
            if self._account is not None:
                return self._account
            try:
                # Import inside the method so a missing exchangelib or a bad
                # env doesn't prevent the process from booting.
                from exchangelib import (  # type: ignore[import-not-found]
                    Account, Configuration, Credentials, DELEGATE, FaultTolerance,
                )
                creds = Credentials(
                    username=settings.exchange_user,
                    password=settings.exchange_password,
                )
                config = Configuration(
                    service_endpoint=settings.ews_effective_url,
                    credentials=creds,
                    retry_policy=FaultTolerance(max_wait=60),
                )
                email = settings.exchange_email or settings.exchange_user
                self._account = Account(
                    primary_smtp_address=email,
                    config=config,
                    autodiscover=False,
                    access_type=DELEGATE,
                )
                # Triggers a real request to prove credentials work.
                _ = self._account.root
                logger.info("EWS account initialized for %s", email)
                self._account_err = None
            except Exception as e:
                self._account = None
                self._account_err = f"{type(e).__name__}: {e}"
                logger.warning("EWS init failed: %s", self._account_err)
                raise BackendError(self._account_err) from e
        return self._account

    # --- MailBackend -------------------------------------------------
    def healthcheck(self) -> bool:
        try:
            acct = self._account_or_raise()
            # Cheap read against a known folder; confirms auth + reachability.
            _ = acct.inbox.name  # type: ignore[attr-defined]
            return True
        except Exception as e:
            logger.debug("EWS healthcheck failed: %s", e)
            return False

    def last_error(self) -> Optional[str]:
        return self._account_err

    def list_folders(self) -> list[FolderInfo]:
        acct = self._account_or_raise()
        result: list[FolderInfo] = []
        # Enumerate the common well-known roots by name, then flatten one level.
        seen: set[str] = set()
        for attr, tcode in _EWS_FOLDER_TYPE.items():
            folder = getattr(acct, attr, None)
            if folder is None:
                continue
            fid = str(folder.id)
            if fid in seen:
                continue
            seen.add(fid)
            result.append(FolderInfo(
                id=fid, name=folder.name, type=tcode,
                parent=str(folder.parent.id) if getattr(folder, "parent", None) else None,
            ))
        return result

    def get_items_since(
        self,
        folder_id: str,
        since: Optional[datetime],
        limit: int = 50,
        include_body: bool = True,
    ) -> list[MailItem]:
        acct = self._account_or_raise()

        # exchangelib lets us look up a folder by id via root/get_folder
        try:
            from exchangelib import FolderId  # type: ignore[import-not-found]
            folder = acct.root.get_folder(FolderId(id=folder_id))
        except Exception as e:
            raise BackendError(f"folder lookup failed: {e}") from e

        qs = folder.all().order_by("-datetime_received")
        if since is not None:
            qs = qs.filter(datetime_received__gt=since)
        qs = qs[: max(1, min(limit, 500))]

        items: list[MailItem] = []
        for m in qs:
            items.append(self._to_mail_item(m, include_body=include_body))
        return items

    def get_item(self, folder_id: str, server_id: str) -> Optional[MailItem]:
        acct = self._account_or_raise()
        try:
            from exchangelib import ItemId  # type: ignore[import-not-found]
            item = acct.root.get_item(ItemId(id=server_id))
            return self._to_mail_item(item, include_body=True)
        except Exception as e:
            logger.warning("EWS get_item(%s) failed: %s", server_id, e)
            return None

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: Optional[list[str]] = None,
        body_is_html: bool = False,
    ) -> None:
        acct = self._account_or_raise()
        from exchangelib import HTMLBody, Message  # type: ignore[import-not-found]

        msg = Message(
            account=acct,
            subject=subject,
            body=HTMLBody(body) if body_is_html else body,
            to_recipients=list(to),
            cc_recipients=list(cc or []),
        )
        msg.send()

    # --- helpers -----------------------------------------------------
    @staticmethod
    def _to_mail_item(m, *, include_body: bool) -> MailItem:
        received = getattr(m, "datetime_received", None)
        if received and received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)

        sender = ""
        if getattr(m, "sender", None) is not None:
            sender = getattr(m.sender, "email_address", "") or getattr(m.sender, "name", "")
        to = ", ".join(
            (r.email_address or "") for r in (getattr(m, "to_recipients", None) or [])
        )
        cc = ", ".join(
            (r.email_address or "") for r in (getattr(m, "cc_recipients", None) or [])
        )

        body_text = ""
        body_is_html = False
        if include_body and getattr(m, "body", None):
            body_text = str(m.body)
            body_is_html = str(type(m.body).__name__).lower().startswith("html")

        return MailItem(
            backend="ews",
            server_id=str(m.id),
            message_id=getattr(m, "message_id", "") or "",
            subject=getattr(m, "subject", "") or "",
            sender=sender,
            to=to,
            cc=cc,
            received=received,
            read=bool(getattr(m, "is_read", False)),
            has_attachments=bool(getattr(m, "has_attachments", False)),
            body=body_text,
            body_is_html=body_is_html,
        )
