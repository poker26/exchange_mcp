"""EWS driver backed by exchangelib.

Initialization is lazy so the process can start even if EWS is
unreachable at boot. healthcheck() is the canonical reachability probe.

All public methods are serialized with an operation lock so parallel MCP
requests (e.g. Ping + CallTool) do not hammer Exchange and trigger
backoff. Folder metadata is cached to avoid re-listing on every mail call.
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import settings
from ..datetime_util import parse_iso_datetime
from .base import (
    AttachmentData,
    AttachmentInfo,
    BackendError,
    CalendarItem,
    CalendarUpdateError,
    ContactItem,
    FolderInfo,
    MailBackend,
    MailItem,
)

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
_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_MAX_EVENT_SUBJECT_LEN = 500
_MAX_EVENT_BODY_LEN = 50_000

_SEND_MEETING_INVITATION_ALIASES = {
    "to_all": "SendToAllAndSaveCopy",
    "to_changed": "SendToChangedAndSaveCopy",
    "save_only": "SendToNone",
}

_ssl_adapter_configured = False


def _folder_id_type():
    try:
        from exchangelib import FolderId  # type: ignore[import-not-found]
    except ImportError:
        from exchangelib.properties import FolderId  # type: ignore[import-not-found]
    return FolderId


def _item_id_type():
    try:
        from exchangelib import ItemId  # type: ignore[import-not-found]
    except ImportError:
        from exchangelib.properties import ItemId  # type: ignore[import-not-found]
    return ItemId


def _fetch_item_by_id(account, item_id: str):
    """Load any mailbox item by EWS id (exchangelib 5.x has no root.get_item)."""
    fetched = list(account.fetch(ids=[_item_id_type()(id=item_id)]))
    if not fetched:
        raise BackendError(f"item {item_id!r} not found")
    return fetched[0]


def _to_ews_datetime(value: datetime) -> datetime:
    """Convert stdlib datetime to EWSDateTime for exchangelib filters."""
    from exchangelib.ewsdatetime import EWSDateTime  # type: ignore[import-not-found]

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return EWSDateTime.from_datetime(value)


def _to_plain_utc_datetime(value: datetime) -> datetime:
    """Normalize EWSDateTime to aware stdlib UTC for state and JSON."""
    from exchangelib.ewsdatetime import EWSDateTime  # type: ignore[import-not-found]

    if isinstance(value, EWSDateTime):
        return datetime.fromtimestamp(value.timestamp(), tz=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _configure_ssl_adapter() -> None:
    """Map SSL_VERIFY to exchangelib 5.x HTTP adapter (Configuration has no verify=)."""
    global _ssl_adapter_configured
    if _ssl_adapter_configured:
        return
    import requests.adapters
    import urllib3
    from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter  # type: ignore[import-not-found]

    verify_setting = settings.verify
    if verify_setting is False:
        BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
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
        self._calendar_folder_id: Optional[str] = None

    def _run_serialized(self, operation_name: str, operation):
        with self._operation_lock:
            try:
                return operation()
            except (BackendError, CalendarUpdateError):
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
                email_address = (settings.exchange_email or "").strip()
                if "@" not in email_address:
                    raise BackendError(
                        "EXCHANGE_EMAIL must be the mailbox SMTP address "
                        "(e.g. oleg.pokrovskiy@inplatlabs.ru). "
                        f"Current value: {email_address!r}. "
                        "Do not use OFFICE\\user here — that belongs in EXCHANGE_USER only."
                    )
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

    def calendar_folder_id(self) -> str:
        def _resolve() -> str:
            if self._calendar_folder_id:
                return self._calendar_folder_id
            account = self._account_or_raise()
            self._calendar_folder_id = str(account.calendar.id)  # type: ignore[attr-defined]
            return self._calendar_folder_id

        return self._run_serialized("calendar_folder_id", _resolve)

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
                folder = account.root.get_folder(_folder_id_type()(id=folder_id))
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
                query_set = query_set.filter(
                    datetime_received__gt=_to_ews_datetime(since),
                )
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
                item = self._get_message_item(account, server_id)
                return self._to_mail_item(item, include_body=True)
            except Exception as exc:
                logger.warning("EWS get_item(%s) failed: %s", server_id, exc)
                return None

        return self._run_serialized("get_item", _fetch)

    def get_email_by_id(self, item_id: str) -> MailItem:
        def _fetch() -> MailItem:
            account = self._account_or_raise()
            item = self._get_message_item(account, item_id)
            return self._to_mail_item(item, include_body=True)

        return self._run_serialized("get_email_by_id", _fetch)

    def mark_email_read(self, item_id: str, is_read: bool) -> None:
        def _update() -> None:
            account = self._account_or_raise()
            item = self._get_message_item(account, item_id)
            item.is_read = is_read
            item.save(update_fields=["is_read"])

        self._run_serialized("mark_email_read", _update)

    def delete_email(self, item_id: str) -> None:
        def _delete() -> None:
            account = self._account_or_raise()
            item = self._get_message_item(account, item_id)
            if hasattr(item, "move_to_trash"):
                item.move_to_trash()
            else:
                item.move(account.trash)  # type: ignore[attr-defined]

        self._run_serialized("delete_email", _delete)

    def move_email(self, item_id: str, target_folder_id: str) -> None:
        def _move() -> None:
            account = self._account_or_raise()
            item = self._get_message_item(account, item_id)
            target_folder = account.root.get_folder(
                _folder_id_type()(id=target_folder_id),
            )
            item.move(target_folder)

        self._run_serialized("move_email", _move)

    def reply_email(
        self,
        item_id: str,
        body: str,
        reply_all: bool = False,
        body_is_html: bool = False,
    ) -> None:
        def _reply() -> None:
            from exchangelib import HTMLBody  # type: ignore[import-not-found]

            account = self._account_or_raise()
            item = self._get_message_item(account, item_id)
            message_body = HTMLBody(body) if body_is_html else body
            if reply_all:
                item.reply_all(body=message_body)
            else:
                item.reply(body=message_body)

        self._run_serialized("reply_email", _reply)

    def forward_email(
        self,
        item_id: str,
        to: list[str],
        body: str = "",
        cc: Optional[list[str]] = None,
        body_is_html: bool = False,
    ) -> None:
        def _forward() -> None:
            from exchangelib import HTMLBody, Mailbox  # type: ignore[import-not-found]

            account = self._account_or_raise()
            item = self._get_message_item(account, item_id)
            message_body = HTMLBody(body) if body_is_html else body
            item.forward(
                subject=f"FW: {getattr(item, 'subject', '')}",
                body=message_body,
                to_recipients=[Mailbox(email_address=address) for address in to],
                cc_recipients=[
                    Mailbox(email_address=address) for address in (cc or [])
                ],
            )

        self._run_serialized("forward_email", _forward)

    def list_attachments(self, item_id: str) -> list[AttachmentInfo]:
        def _list() -> list[AttachmentInfo]:
            account = self._account_or_raise()
            item = _fetch_item_by_id(account, item_id)
            if not getattr(item, "attachments", None):
                return []
            item.refresh()
            return [
                self._to_attachment_info(attachment)
                for attachment in (item.attachments or [])
            ]

        return self._run_serialized("list_attachments", _list)

    @staticmethod
    def _resolve_send_meeting_invitations(alias: str) -> str:
        normalized = (alias or "to_all").strip().lower()
        resolved = _SEND_MEETING_INVITATION_ALIASES.get(normalized)
        if resolved is None:
            allowed = ", ".join(sorted(_SEND_MEETING_INVITATION_ALIASES))
            raise CalendarUpdateError(
                "INVALID_SEND_MEETING",
                f"send_meeting_invitations must be one of: {allowed}",
            )
        return resolved

    def update_calendar_event(
        self,
        event_id: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
        subject: Optional[str] = None,
        location: Optional[str] = None,
        body: Optional[str] = None,
        body_is_html: bool = False,
        send_meeting_invitations: str = "to_all",
    ) -> CalendarItem:
        def _update() -> CalendarItem:
            from exchangelib import CalendarItem as EwsCalendarItem  # type: ignore[import-not-found]
            from exchangelib import HTMLBody  # type: ignore[import-not-found]

            account = self._account_or_raise()
            try:
                item = _fetch_item_by_id(account, event_id)
            except BackendError as exc:
                raise CalendarUpdateError(
                    "EVENT_NOT_FOUND",
                    str(exc),
                ) from exc
            except Exception as exc:
                raise CalendarUpdateError(
                    "EVENT_NOT_FOUND",
                    f"event {event_id!r} not found: {exc}",
                ) from exc

            if not isinstance(item, EwsCalendarItem):
                raise CalendarUpdateError(
                    "NOT_A_CALENDAR_ITEM",
                    f"item {event_id!r} is not a calendar event",
                )

            if getattr(item, "recurrence", None) is not None:
                raise CalendarUpdateError(
                    "RECURRENCE_UNSUPPORTED",
                    "recurring events cannot be updated yet; edit in Outlook",
                )

            changed_fields: list[str] = []

            if subject is not None and subject.strip():
                if len(subject) > _MAX_EVENT_SUBJECT_LEN:
                    raise CalendarUpdateError(
                        "FIELD_TOO_LONG",
                        f"subject exceeds {_MAX_EVENT_SUBJECT_LEN} characters",
                    )
                item.subject = subject.strip()
                changed_fields.append("subject")

            if location is not None and location.strip():
                item.location = location.strip()
                changed_fields.append("location")

            if body is not None and body.strip():
                if len(body) > _MAX_EVENT_BODY_LEN:
                    raise CalendarUpdateError(
                        "FIELD_TOO_LONG",
                        f"body exceeds {_MAX_EVENT_BODY_LEN} characters",
                    )
                item.body = HTMLBody(body) if body_is_html else body
                changed_fields.append("body")

            if start is not None and start.strip():
                item.start = _to_ews_datetime(parse_iso_datetime(start))
                changed_fields.append("start")

            if end is not None and end.strip():
                item.end = _to_ews_datetime(parse_iso_datetime(end))
                changed_fields.append("end")

            if not changed_fields:
                raise CalendarUpdateError(
                    "NO_FIELDS_TO_UPDATE",
                    "provide at least one non-empty field to update",
                )

            if item.start is not None and item.end is not None:
                start_plain = _to_plain_utc_datetime(item.start)
                end_plain = _to_plain_utc_datetime(item.end)
                if end_plain <= start_plain:
                    raise CalendarUpdateError(
                        "INVALID_TIME_RANGE",
                        "end must be after start",
                    )

            invitation_mode = self._resolve_send_meeting_invitations(
                send_meeting_invitations,
            )
            try:
                item.save(
                    update_fields=changed_fields,
                    send_meeting_invitations=invitation_mode,
                )
                item.refresh()
            except CalendarUpdateError:
                raise
            except Exception as exc:
                raise CalendarUpdateError(
                    "EWS_FAULT",
                    f"failed to save calendar event: {exc}",
                ) from exc

            return self._to_calendar_item(item)

        return self._run_serialized("update_calendar_event", _update)

    def respond_to_event(self, event_id: str, response: str) -> CalendarItem:
        def _respond() -> CalendarItem:
            account = self._account_or_raise()
            item = _fetch_item_by_id(account, event_id)
            response_normalized = response.strip().lower()
            if response_normalized == "accept":
                item.accept(send_response=True)
            elif response_normalized == "decline":
                item.decline(send_response=True)
            elif response_normalized in ("tentative", "tentatively"):
                item.tentatively_accept(send_response=True)
            else:
                raise BackendError(
                    "response must be accept, decline, or tentative",
                )
            return self._to_calendar_item(item)

        return self._run_serialized("respond_to_event", _respond)

    def get_calendar_items(
        self,
        folder_id: Optional[str],
        date_from: datetime,
        date_to: datetime,
        limit: int = 200,
    ) -> list[CalendarItem]:
        def _fetch() -> list[CalendarItem]:
            account = self._account_or_raise()
            if folder_id:
                try:
                    folder = account.root.get_folder(_folder_id_type()(id=folder_id))
                except Exception as exc:
                    raise BackendError(f"folder lookup failed: {exc}") from exc
            else:
                folder = account.calendar

            field_names = [
                "id",
                "uid",
                "subject",
                "location",
                "organizer",
                "start",
                "end",
                "last_modified_time",
                "is_all_day",
                "body",
                "required_attendees",
                "optional_attendees",
            ]
            query_set = (
                folder.view(
                    start=_to_ews_datetime(date_from),
                    end=_to_ews_datetime(date_to),
                )
                .only(*field_names)
            )
            query_set = query_set[: max(1, min(limit, 500))]

            return [self._to_calendar_item(event) for event in query_set]

        return self._run_serialized("get_calendar_items", _fetch)

    def get_calendar_items_since(
        self,
        folder_id: Optional[str],
        since: Optional[datetime],
        limit: int = 50,
    ) -> list[CalendarItem]:
        now = datetime.now(timezone.utc)
        if since is None:
            date_from = now - timedelta(days=14)
        else:
            date_from = since - timedelta(minutes=5)
        date_to = now + timedelta(days=365)
        items = self.get_calendar_items(
            folder_id, date_from, date_to, limit=max(limit * 3, 100),
        )
        if since is None:
            return items[:limit]

        filtered: list[CalendarItem] = []
        for event in items:
            event_time = event.last_modified or event.start
            if event_time and event_time > since:
                filtered.append(event)
        filtered.sort(
            key=lambda event: event.last_modified or event.start or now,
            reverse=True,
        )
        return filtered[:limit]

    def create_calendar_event(
        self,
        subject: str,
        start: str,
        end: str,
        location: str = "",
        body: str = "",
        attendees: Optional[list[str]] = None,
        folder_id: Optional[str] = None,
    ) -> CalendarItem:
        def _create() -> CalendarItem:
            account = self._account_or_raise()
            from exchangelib import Attendee, CalendarItem as EwsCalendarItem  # type: ignore[import-not-found]
            from exchangelib import Mailbox  # type: ignore[import-not-found]

            if folder_id:
                folder = account.root.get_folder(_folder_id_type()(id=folder_id))
            else:
                folder = account.calendar

            start_time = _to_ews_datetime(parse_iso_datetime(start))
            end_time = _to_ews_datetime(parse_iso_datetime(end))
            attendee_list = [
                Attendee(mailbox=Mailbox(email_address=address))
                for address in (attendees or [])
                if address.strip()
            ]
            event = EwsCalendarItem(
                account=account,
                folder=folder,
                subject=subject,
                start=start_time,
                end=end_time,
                location=location,
                body=body,
                required_attendees=attendee_list,
            )
            event.save()
            return self._to_calendar_item(event)

        return self._run_serialized("create_calendar_event", _create)

    def search_emails(
        self,
        query: str,
        limit: int = 20,
        folder_id: Optional[str] = None,
        search_body: bool = False,
    ) -> list[MailItem]:
        def _search() -> list[MailItem]:
            from exchangelib import Q  # type: ignore[import-not-found]

            account = self._account_or_raise()
            search_text = query.strip()
            if not search_text:
                return []

            if folder_id:
                folder = account.root.get_folder(_folder_id_type()(id=folder_id))
            else:
                folder = account.inbox

            filter_query = (
                Q(subject__icontains=search_text)
                | Q(sender__icontains=search_text)
            )
            if search_body:
                filter_query = filter_query | Q(body__icontains=search_text)
            field_names = [
                "id",
                "message_id",
                "subject",
                "sender",
                "to_recipients",
                "datetime_received",
                "is_read",
                "has_attachments",
            ]
            query_set = (
                folder.filter(filter_query)
                .only(*field_names)
                .order_by("-datetime_received")
            )
            query_set = query_set[: max(1, min(limit, 100))]
            return [self._to_mail_item(message, include_body=False) for message in query_set]

        return self._run_serialized("search_emails", _search)

    def get_contacts(
        self,
        folder_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[ContactItem]:
        def _fetch() -> list[ContactItem]:
            account = self._account_or_raise()
            if folder_id:
                folder = account.root.get_folder(_folder_id_type()(id=folder_id))
            else:
                folder = account.contacts

            field_names = [
                "id",
                "display_name",
                "email_addresses",
                "phone_numbers",
                "company_name",
            ]
            query_set = (
                folder.all()
                .only(*field_names)
                .order_by("display_name")
            )
            query_set = query_set[: max(1, min(limit, 200))]
            return [self._to_contact_item(contact) for contact in query_set]

        return self._run_serialized("get_contacts", _fetch)

    def get_attachment(
        self,
        item_id: str,
        attachment_id: str,
    ) -> AttachmentData:
        def _fetch() -> AttachmentData:
            account = self._account_or_raise()
            item = _fetch_item_by_id(account, item_id)
            if not getattr(item, "attachments", None):
                raise BackendError("item has no attachments")

            for attachment in item.attachments:
                candidate_ids = {self._attachment_id(attachment)}
                if attachment_id not in candidate_ids:
                    continue

                content = getattr(attachment, "content", None)
                if content is None:
                    raise BackendError("attachment has no inline content (may be embedded)")

                raw_bytes = bytes(content)
                if len(raw_bytes) > _MAX_ATTACHMENT_BYTES:
                    raise BackendError(
                        f"attachment too large ({len(raw_bytes)} bytes, "
                        f"max {_MAX_ATTACHMENT_BYTES})",
                    )

                return AttachmentData(
                    backend="ews",
                    item_id=item_id,
                    attachment_id=attachment_id,
                    name=getattr(attachment, "name", "") or "attachment",
                    content_type=getattr(attachment, "content_type", "") or "application/octet-stream",
                    size=len(raw_bytes),
                    content_base64=base64.b64encode(raw_bytes).decode("ascii"),
                )

            raise BackendError(f"attachment {attachment_id!r} not found on item")

        return self._run_serialized("get_attachment", _fetch)

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
    def _get_message_item(account, item_id: str):
        item = _fetch_item_by_id(account, item_id)
        if not hasattr(item, "reply"):
            raise BackendError(f"item {item_id!r} is not an email message")
        return item

    @staticmethod
    def _attachment_id(attachment) -> str:
        return (
            str(getattr(attachment, "attachment_id", "") or "")
            or str(getattr(getattr(attachment, "attachment_id", None), "id", "") or "")
            or str(getattr(attachment, "id", "") or "")
        )

    @classmethod
    def _to_attachment_info(cls, attachment) -> AttachmentInfo:
        content = getattr(attachment, "content", None)
        size = len(content) if content is not None else int(getattr(attachment, "size", 0) or 0)
        return AttachmentInfo(
            attachment_id=cls._attachment_id(attachment),
            name=getattr(attachment, "name", "") or "attachment",
            content_type=getattr(attachment, "content_type", "") or "application/octet-stream",
            size=size,
            is_inline=bool(getattr(attachment, "is_inline", False)),
        )

    @staticmethod
    def _to_mail_item(message, *, include_body: bool) -> MailItem:
        received = getattr(message, "datetime_received", None)
        if received is not None:
            received = _to_plain_utc_datetime(received)

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

    @staticmethod
    def _to_calendar_item(event) -> CalendarItem:
        start_value = getattr(event, "start", None)
        end_value = getattr(event, "end", None)
        if start_value is not None:
            start_value = _to_plain_utc_datetime(start_value)
        if end_value is not None:
            end_value = _to_plain_utc_datetime(end_value)

        organizer = ""
        if getattr(event, "organizer", None) is not None:
            organizer = (
                getattr(event.organizer, "email_address", "")
                or getattr(event.organizer, "name", "")
            )

        attendees: list[str] = []
        for attendee_field in ("required_attendees", "optional_attendees"):
            for attendee in getattr(event, attendee_field, None) or []:
                address = (
                    getattr(attendee, "email_address", "")
                    or getattr(attendee, "name", "")
                )
                if address:
                    attendees.append(address)

        body_text = ""
        if getattr(event, "body", None):
            body_text = str(event.body)

        last_modified_value = getattr(event, "last_modified_time", None)
        if last_modified_value is not None:
            last_modified_value = _to_plain_utc_datetime(last_modified_value)

        return CalendarItem(
            backend="ews",
            server_id=str(event.id),
            uid=getattr(event, "uid", "") or "",
            subject=getattr(event, "subject", "") or "",
            location=getattr(event, "location", "") or "",
            organizer=organizer,
            start=start_value,
            end=end_value,
            last_modified=last_modified_value,
            all_day=bool(getattr(event, "is_all_day", False)),
            body=body_text,
            attendees=attendees,
        )

    @staticmethod
    def _to_contact_item(contact) -> ContactItem:
        email_address = ""
        for entry in getattr(contact, "email_addresses", None) or []:
            email_address = (
                getattr(entry, "email", "")
                or getattr(entry, "email_address", "")
                or str(entry)
            )
            if email_address:
                break

        phone_number = ""
        for entry in getattr(contact, "phone_numbers", None) or []:
            phone_number = getattr(entry, "phone_number", "") or str(entry)
            if phone_number:
                break

        return ContactItem(
            backend="ews",
            server_id=str(contact.id),
            display_name=getattr(contact, "display_name", "") or "",
            email=email_address,
            phone=phone_number,
            company=getattr(contact, "company_name", "") or "",
        )
