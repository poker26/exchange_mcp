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
    all_day: bool = False
    body: str = ""
    attendees: list = field(default_factory=list)

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
            "all_day": self.all_day,
            "body": self.body,
            "attendees": self.attendees,
        }


class BackendError(Exception):
    """Raised by a driver on an unrecoverable protocol error.

    The router treats BackendError as an unhealthy signal and falls back
    to the other channel. Transient errors should be retried inside the
    driver (e.g. EAS `_post` already does that) before surfacing.
    """


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
