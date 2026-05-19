"""EWS driver backed by exchangelib.

Initialization is lazy so the process can start even if EWS is
unreachable at boot. healthcheck() is the canonical reachability probe.

All public methods are serialized with an operation lock so parallel MCP
requests (e.g. Ping + CallTool) do not hammer Exchange and trigger
backoff. Folder metadata is cached to avoid re-listing on every mail call.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import settings
from .base import BackendError, FolderInfo, MailBackend, MailItem

logger = logging.getLogger(__name__)

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

_DEFAULT_FOLDERS_CACHE_TTL = 300.0

_ssl_adapter_configured = False


def _configure_ssl_adapter() -> None:
    """Map SSL_VERIFY to exchangelib 5.x HTTP adapter (Configuration has no verify=)."""
    global _ssl_adapter_configured
    if _ssl_adapter_configured:
        return
    import requests.adapters
    from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter  # type: ignore[import-not-found]

    verify_setting = settings.verify
    if verify_setting is False:
        BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter
        logger.info("EWS TLS verification disabled (SSL_VERIFY=false)")
    else:
        BaseProtocol.HTTP_ADAPTER_CLS = requests.adapters.HTTPAdapter
        if isinstance(verify_setting, str):
            logger.info("EWS TLS verification uses CA bundle: %s", verify_setting)
    _ssl_adapter_configured = True


class EWSBackend:
    name = "ews"

    def __init__(self) -> None:
        self._account = None
        self._account_err: Optional[str] = None
        self._init_lock = threading.Lock()
        self._operation_lock = threading.Lock()
        self._folders_cache: Optional[list[FolderInfo]] = None
        self._folders_cached_at: float = 0.0
        self._inbox_folder_id: Optional[str] = None

    def _run_serialized(self, operation_name: str, operation):
        with self._operation_lock:
            try:
                return operation()
            except BackendError:
                raise
            except Exception as exc:
                raise BackendError(f"{operation_name}: {exc}") from exc

    def _account_or_raise(self):
        if self._account is not None:
            return self._account
        with self._init_lock:
            if self._account is not None:
                return self._account
            try:
                from exchangelib import (  # type: ignore[import-not-found]
                    Account,
                    Configuration,
                    Credentials,
                    DELEGATE,
                    FaultTolerance,
                )

                _configure_ssl_adapter()
                credentials = Credentials(
                    username=settings.exchange_user,
                    password=settings.exchange_password,
                )
                configuration = Configuration(
                    service_endpoint=settings.ews_effective_url,
                    credentials=credentials,
                    retry_policy=FaultTolerance(max_wait=30),
                )
                email_address = settings.exchange_email or settings.exchange_user
                account = Account(
                    primary_smtp_address=email_address,
                    config=configuration,
                    autodiscover=False,
                    access_type=DELEGATE,
                )
                _ = account.root
                self._account = account
                self._inbox_folder_id = str(account.inbox.id)  # type: ignore[attr-defined]
                logger.info("EWS account initialized for %s", email_address)
                self._account_err = None
            except Exception as exc:
                self._account = None
                self._inbox_folder_id = None
                self._account_err = f"{type(exc).__name__}: {exc}"
                logger.warning("EWS init failed: %s", self._account_err)
                raise BackendError(self._account_err) from exc
        return self._account

    def healthcheck(self) -> bool:
        def _check() -> bool:
            if self._account is not None:
                return True
            self._account_or_raise()
            return True

        try:
            return self._run_serialized("healthcheck", _check)
        except Exception as exc:
            logger.debug("EWS healthcheck failed: %s", exc)
            return False

    def last_error(self) -> Optional[str]:
        return self._account_err

    def inbox_folder_id(self) -> str:
        def _resolve() -> str:
            if self._inbox_folder_id:
                return self._inbox_folder_id
            account = self._account_or_raise()
            self._inbox_folder_id = str(account.inbox.id)  # type: ignore[attr-defined]
            return self._inbox_folder_id

        return self._run_serialized("inbox_folder_id", _resolve)

    def list_folders(self) -> list[FolderInfo]:
        def _list() -> list[FolderInfo]:
            cache_ttl = getattr(
                settings, "ews_folders_cache_ttl", _DEFAULT_FOLDERS_CACHE_TTL,
            )
            now = time.monotonic()
            if (
                self._folders_cache is not None
                and now - self._folders_cached_at < cache_ttl
            ):
                return list(self._folders_cache)

            account = self._account_or_raise()
            result: list[FolderInfo] = []
            seen: set[str] = set()
            for attribute_name, type_code in _EWS_FOLDER_TYPE.items():
                folder = getattr(account, attribute_name, None)
                if folder is None:
                    continue
                folder_id = str(folder.id)
                if folder_id in seen:
                    continue
                seen.add(folder_id)
                result.append(FolderInfo(
                    id=folder_id,
                    name=folder.name,
                    type=type_code,
                    parent=(
                        str(folder.parent.id)
                        if getattr(folder, "parent", None)
                        else None
                    ),
                ))
            self._folders_cache = result
            self._folders_cached_at = now
            return list(result)

        return self._run_serialized("list_folders", _list)

    def get_items_since(
        self,
        folder_id: str,
        since: Optional[datetime],
        limit: int = 50,
        include_body: bool = True,
    ) -> list[MailItem]:
        def _fetch() -> list[MailItem]:
            account = self._account_or_raise()
            try:
                from exchangelib import FolderId  # type: ignore[import-not-found]
                folder = account.root.get_folder(FolderId(id=folder_id))
            except Exception as exc:
                raise BackendError(f"folder lookup failed: {exc}") from exc

            field_names = [
                "id",
                "message_id",
                "subject",
                "sender",
                "to_recipients",
                "cc_recipients",
                "datetime_received",
                "is_read",
                "has_attachments",
            ]
            if include_body:
                field_names.append("body")

            query_set = (
                folder.all()
                .only(*field_names)
                .order_by("-datetime_received")
            )
            if since is not None:
                query_set = query_set.filter(datetime_received__gt=since)
            query_set = query_set[: max(1, min(limit, 500))]

            return [
                self._to_mail_item(message, include_body=include_body)
                for message in query_set
            ]

        return self._run_serialized("get_items_since", _fetch)

    def get_item(self, folder_id: str, server_id: str) -> Optional[MailItem]:
        def _fetch() -> Optional[MailItem]:
            account = self._account_or_raise()
            try:
                from exchangelib import ItemId  # type: ignore[import-not-found]
                item = account.root.get_item(ItemId(id=server_id))
                return self._to_mail_item(item, include_body=True)
            except Exception as exc:
                logger.warning("EWS get_item(%s) failed: %s", server_id, exc)
                return None

        return self._run_serialized("get_item", _fetch)

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: Optional[list[str]] = None,
        body_is_html: bool = False,
    ) -> None:
        def _send() -> None:
            account = self._account_or_raise()
            from exchangelib import HTMLBody, Message  # type: ignore[import-not-found]

            message = Message(
                account=account,
                subject=subject,
                body=HTMLBody(body) if body_is_html else body,
                to_recipients=list(to),
                cc_recipients=list(cc or []),
            )
            message.send()

        self._run_serialized("send_email", _send)

    @staticmethod
    def _to_mail_item(message, *, include_body: bool) -> MailItem:
        received = getattr(message, "datetime_received", None)
        if received and received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)

        sender = ""
        if getattr(message, "sender", None) is not None:
            sender = (
                getattr(message.sender, "email_address", "")
                or getattr(message.sender, "name", "")
            )
        to_addresses = ", ".join(
            (recipient.email_address or "")
            for recipient in (getattr(message, "to_recipients", None) or [])
        )
        cc_addresses = ", ".join(
            (recipient.email_address or "")
            for recipient in (getattr(message, "cc_recipients", None) or [])
        )

        body_text = ""
        body_is_html = False
        if include_body and getattr(message, "body", None):
            body_text = str(message.body)
            body_is_html = str(type(message.body).__name__).lower().startswith("html")

        return MailItem(
            backend="ews",
            server_id=str(message.id),
            message_id=getattr(message, "message_id", "") or "",
            subject=getattr(message, "subject", "") or "",
            sender=sender,
            to=to_addresses,
            cc=cc_addresses,
            received=received,
            read=bool(getattr(message, "is_read", False)),
            has_attachments=bool(getattr(message, "has_attachments", False)),
            body=body_text,
            body_is_html=body_is_html,
        )
