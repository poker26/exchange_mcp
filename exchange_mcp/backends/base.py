"""Common interface and DTO shared by EWS and EAS drivers.

Both drivers normalize their native objects to `MailItem` / `FolderInfo`
so the router and MCP tools don't have to care which channel served a
request. InternetMessageId is canonical for dedup across channels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, Optional, runtime_checkable


@dataclass
class FolderInfo:
    id: str
    name: str
    # 2=Inbox, 5=Sent, 6=Deleted, 8=Calendar, 9=Contacts, 17=Calendar (generic);
    # follows EAS FolderSync "Type". EWS driver maps its well-known names to
    # the same numeric codes so the REST/MCP layer stays protocol-agnostic.
    type: Optional[int] = None
    parent: Optional[str] = None


@dataclass
class MailItem:
    backend: str               # "ews" or "eas"
    server_id: str             # channel-native id; not portable across channels
    message_id: str            # RFC 5322 Message-ID — portable, dedup key
    subject: str = ""
    sender: str = ""
    to: str = ""
    cc: str = ""
    received: Optional[datetime] = None  # UTC
    read: bool = False
    has_attachments: bool = False
    preview: str = ""
    body: str = ""
    body_is_html: bool = False

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "id": self.server_id,
            "message_id": self.message_id,
            "subject": self.subject,
            "from": self.sender,
            "to": self.to,
            "cc": self.cc,
            "date": self.received.isoformat() if self.received else "",
            "read": self.read,
            "has_attachments": self.has_attachments,
            "preview": self.preview,
            "body": self.body,
            "body_is_html": self.body_is_html,
        }


@dataclass
class CalendarItem:
    backend: str
    server_id: str
    uid: str                   # iCalendar UID — portable, dedup key
    subject: str = ""
    location: str = ""
    organizer: str = ""
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    last_modified: Optional[datetime] = None
    all_day: bool = False
    body: str = ""
    attendees: list = field(default_factory=list)
    is_cancelled: bool = False

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "id": self.server_id,
            "uid": self.uid,
            "subject": self.subject,
            "location": self.location,
            "organizer": self.organizer,
            "start": self.start.isoformat() if self.start else "",
            "end": self.end.isoformat() if self.end else "",
            "last_modified": (
                self.last_modified.isoformat() if self.last_modified else ""
            ),
            "all_day": self.all_day,
            "body": self.body,
            "attendees": self.attendees,
            "is_cancelled": self.is_cancelled,
        }


@dataclass
class ContactItem:
    backend: str
    server_id: str
    display_name: str = ""
    email: str = ""
    phone: str = ""
    company: str = ""

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "id": self.server_id,
            "display_name": self.display_name,
            "email": self.email,
            "phone": self.phone,
            "company": self.company,
        }


@dataclass
class AttachmentInfo:
    attachment_id: str
    name: str
    content_type: str
    size: int
    is_inline: bool = False

    def to_dict(self) -> dict:
        return {
            "attachment_id": self.attachment_id,
            "name": self.name,
            "content_type": self.content_type,
            "size": self.size,
            "is_inline": self.is_inline,
        }


@dataclass
class AttachmentData:
    backend: str
    item_id: str
    attachment_id: str
    name: str
    content_type: str
    size: int
    content_base64: str

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "item_id": self.item_id,
            "attachment_id": self.attachment_id,
            "name": self.name,
            "content_type": self.content_type,
            "size": self.size,
            "content_base64": self.content_base64,
        }


class BackendError(Exception):
    """Raised by a driver on an unrecoverable protocol error.

    The router treats BackendError as an unhealthy signal and falls back
    to the other channel. Transient errors should be retried inside the
    driver (e.g. EAS `_post` already does that) before surfacing.
    """


class CalendarUpdateError(Exception):
    """Predictable calendar update failure with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@runtime_checkable
class MailBackend(Protocol):
    name: str                  # "ews" or "eas"

    def healthcheck(self) -> bool: ...
    def list_folders(self) -> list[FolderInfo]: ...

    def get_items_since(
        self,
        folder_id: str,
        since: Optional[datetime],
        limit: int = 50,
        include_body: bool = True,
    ) -> list[MailItem]: ...

    def get_item(self, folder_id: str, server_id: str) -> Optional[MailItem]: ...

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: Optional[list[str]] = None,
        body_is_html: bool = False,
    ) -> None: ...
