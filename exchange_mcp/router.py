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

import base64
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, TypeVar

from .backends.base import (
    AttachmentData,
    AttachmentInfo,
    BackendError,
    CalendarItem,
    CalendarUpdateError,
    ContactItem,
    FolderInfo,
    MailItem,
)
from .backends.ews import EWSBackend
from .config import settings
from . import minio_stage
from .meeting_invite import looks_like_meeting_invite, parse_vevent_from_ics
from .state import SharedState

logger = logging.getLogger(__name__)

_SAFETY_MARGIN = timedelta(minutes=5)
_HEALTH_TTL = 60.0

ReturnType = TypeVar("ReturnType")


_CALENDAR_DELETE_LOOKBACK = timedelta(days=60)
_CALENDAR_DELETE_LOOKAHEAD = timedelta(days=400)


def _calendar_event_marker(event: CalendarItem) -> str:
    if event.last_modified:
        return event.last_modified.astimezone(timezone.utc).isoformat()
    body_signature = (event.body or "")[:512]
    start_value = event.start.isoformat() if event.start else ""
    end_value = event.end.isoformat() if event.end else ""
    return f"{start_value}|{end_value}|{event.subject}|{event.location}|{body_signature}"


def _calendar_state_from_event(event: CalendarItem) -> dict:
    return {
        "marker": _calendar_event_marker(event),
        "start": event.start.isoformat() if event.start else "",
        "server_id": event.server_id,
        "subject": event.subject,
    }


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
        except CalendarUpdateError:
            raise
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

    def get_calendar(
        self,
        folder_id: Optional[str],
        date_from: datetime,
        date_to: datetime,
        limit: int = 200,
    ) -> tuple[list[CalendarItem], str]:
        def _fetch(ews: EWSBackend) -> list[CalendarItem]:
            return ews.get_calendar_items(
                folder_id, date_from, date_to, limit=limit,
            )

        items, _backend = self._execute("get_calendar", _fetch)
        return items, "ews"

    def get_new_calendar(
        self,
        folder_id: Optional[str],
        limit: int = 50,
    ) -> tuple[list[CalendarItem], list[CalendarItem], list[dict], str, bool]:
        def _resolve_folder(ews: EWSBackend) -> str:
            return folder_id or ews.calendar_folder_id()

        resolved_folder, _backend = self._execute(
            "resolve_calendar_folder", _resolve_folder,
        )
        state_key = f"cal:{resolved_folder}"
        cursor = self.state.get_cursor(state_key)
        is_initial = cursor is None
        since = (cursor - _SAFETY_MARGIN) if cursor else None

        if is_initial:
            def _seed(ews: EWSBackend) -> list[CalendarItem]:
                now = datetime.now(timezone.utc)
                return ews.get_calendar_items(
                    folder_id,
                    now - _CALENDAR_DELETE_LOOKBACK,
                    now + _CALENDAR_DELETE_LOOKAHEAD,
                    limit=500,
                )

            seed_items, _backend = self._execute("seed_calendar", _seed)
            max_marker: Optional[datetime] = None
            for event in seed_items:
                if not event.uid:
                    continue
                self.state.set_calendar_event(
                    state_key, event.uid, _calendar_state_from_event(event),
                )
                marker = event.last_modified or event.start
                if marker and (max_marker is None or marker > max_marker):
                    max_marker = marker
            if max_marker is not None:
                self.state.set_cursor(state_key, max_marker)
            return [], [], [], "ews", True

        known_events = self.state.get_calendar_events(state_key)
        if not known_events and cursor is not None:
            def _migrate_seed(ews: EWSBackend) -> list[CalendarItem]:
                now = datetime.now(timezone.utc)
                return ews.get_calendar_items(
                    folder_id,
                    now - _CALENDAR_DELETE_LOOKBACK,
                    now + _CALENDAR_DELETE_LOOKAHEAD,
                    limit=500,
                )

            seed_items, _backend = self._execute(
                "migrate_calendar_state", _migrate_seed,
            )
            for event in seed_items:
                if event.uid:
                    self.state.set_calendar_event(
                        state_key, event.uid, _calendar_state_from_event(event),
                    )
            known_events = self.state.get_calendar_events(state_key)

        def _fetch(ews: EWSBackend) -> list[CalendarItem]:
            return ews.get_calendar_items_since(folder_id, since, limit=limit)

        items, _backend = self._execute("get_new_calendar", _fetch)

        known_events = self.state.get_calendar_events(state_key)
        added_items: list[CalendarItem] = []
        changed_items: list[CalendarItem] = []
        deleted_items: list[dict] = []
        max_marker: Optional[datetime] = None

        for event in items:
            if not event.uid:
                continue
            marker_time = event.last_modified or event.start
            if marker_time and (max_marker is None or marker_time > max_marker):
                max_marker = marker_time

            if event.is_cancelled:
                if event.uid in known_events:
                    deleted_items.append({
                        "uid": event.uid,
                        "server_id": known_events[event.uid].get("server_id", event.server_id),
                        "subject": event.subject or known_events[event.uid].get("subject", ""),
                        "reason": "cancelled",
                    })
                    self.state.remove_calendar_event(state_key, event.uid)
                continue

            marker = _calendar_event_marker(event)
            previous = known_events.get(event.uid)
            if previous is None:
                added_items.append(event)
            elif previous.get("marker") != marker:
                changed_items.append(event)

            self.state.set_calendar_event(
                state_key, event.uid, _calendar_state_from_event(event),
            )
            known_events[event.uid] = _calendar_state_from_event(event)

        now = datetime.now(timezone.utc)

        def _list_uids(ews: EWSBackend) -> set[str]:
            return ews.list_calendar_uids_in_range(
                folder_id,
                now - _CALENDAR_DELETE_LOOKBACK,
                now + _CALENDAR_DELETE_LOOKAHEAD,
                limit=500,
            )

        current_uids, _backend = self._execute("list_calendar_uids", _list_uids)
        for uid, previous in list(known_events.items()):
            if uid in current_uids:
                continue
            deleted_items.append({
                "uid": uid,
                "server_id": previous.get("server_id", ""),
                "subject": previous.get("subject", ""),
                "reason": "removed",
            })
            self.state.remove_calendar_event(state_key, uid)

        if max_marker is not None:
            self.state.set_cursor(state_key, max_marker)

        return added_items, changed_items, deleted_items, "ews", False

    def create_calendar_event(
        self,
        subject: str,
        start: str,
        end: str,
        location: str = "",
        body: str = "",
        attendees: Optional[list[str]] = None,
    ) -> tuple[CalendarItem, str]:
        def _create(ews: EWSBackend) -> CalendarItem:
            return ews.create_calendar_event(
                subject=subject,
                start=start,
                end=end,
                location=location,
                body=body,
                attendees=attendees,
            )

        item, _backend = self._execute("create_calendar_event", _create)
        return item, "ews"

    def get_email(self, item_id: str) -> tuple[MailItem, str]:
        def _fetch(ews: EWSBackend) -> MailItem:
            return ews.get_email_by_id(item_id)

        item, _backend = self._execute("get_email", _fetch)
        return item, "ews"

    def mark_email_read(self, item_id: str, is_read: bool) -> str:
        def _update(ews: EWSBackend) -> None:
            ews.mark_email_read(item_id, is_read)

        self._execute("mark_email_read", _update)
        return "ews"

    def delete_email(self, item_id: str) -> str:
        def _delete(ews: EWSBackend) -> None:
            ews.delete_email(item_id)

        self._execute("delete_email", _delete)
        return "ews"

    def move_email(self, item_id: str, target_folder_id: str) -> str:
        def _move(ews: EWSBackend) -> None:
            ews.move_email(item_id, target_folder_id)

        self._execute("move_email", _move)
        return "ews"

    def reply_email(
        self,
        item_id: str,
        body: str,
        reply_all: bool = False,
        body_is_html: bool = False,
    ) -> str:
        def _reply(ews: EWSBackend) -> None:
            ews.reply_email(
                item_id, body, reply_all=reply_all, body_is_html=body_is_html,
            )

        self._execute("reply_email", _reply)
        return "ews"

    def forward_email(
        self,
        item_id: str,
        to: list[str],
        body: str = "",
        cc: Optional[list[str]] = None,
        body_is_html: bool = False,
    ) -> str:
        def _forward(ews: EWSBackend) -> None:
            ews.forward_email(
                item_id, to, body=body, cc=cc, body_is_html=body_is_html,
            )

        self._execute("forward_email", _forward)
        return "ews"

    def search_emails(
        self,
        query: str,
        limit: int = 20,
        folder_id: Optional[str] = None,
        search_body: bool = False,
    ) -> tuple[list[MailItem], str]:
        def _search(ews: EWSBackend) -> list[MailItem]:
            return ews.search_emails(
                query, limit=limit, folder_id=folder_id, search_body=search_body,
            )

        items, _backend = self._execute("search_emails", _search)
        return items, "ews"

    def list_attachments(self, item_id: str) -> tuple[list[AttachmentInfo], str]:
        def _list(ews: EWSBackend) -> list[AttachmentInfo]:
            return ews.list_attachments(item_id)

        items, _backend = self._execute("list_attachments", _list)
        return items, "ews"

    def respond_to_event(self, event_id: str, response: str) -> tuple[CalendarItem, str]:
        def _respond(ews: EWSBackend) -> CalendarItem:
            return ews.respond_to_event(event_id, response)

        item, _backend = self._execute("respond_to_event", _respond)
        return item, "ews"

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
    ) -> tuple[CalendarItem, str]:
        def _update(ews: EWSBackend) -> CalendarItem:
            return ews.update_calendar_event(
                event_id,
                start=start,
                end=end,
                subject=subject,
                location=location,
                body=body,
                body_is_html=body_is_html,
                send_meeting_invitations=send_meeting_invitations,
            )

        item, _backend = self._execute("update_calendar_event", _update)
        return item, "ews"

    def get_contacts(
        self,
        folder_id: Optional[str],
        limit: int = 50,
    ) -> tuple[list[ContactItem], str]:
        def _fetch(ews: EWSBackend) -> list[ContactItem]:
            return ews.get_contacts(folder_id, limit=limit)

        items, _backend = self._execute("get_contacts", _fetch)
        return items, "ews"

    def get_attachment(
        self,
        item_id: str,
        attachment_id: str,
    ) -> tuple[AttachmentData, str]:
        def _fetch(ews: EWSBackend) -> AttachmentData:
            return ews.get_attachment(item_id, attachment_id)

        data, _backend = self._execute("get_attachment", _fetch)
        return data, "ews"

    def parse_meeting_invite(
        self,
        item_id: str,
        body: str = "",
        subject: str = "",
        has_attachments: bool = False,
    ) -> Optional[dict]:
        """Extract meeting start/end from embedded or attached iCalendar data."""
        if body and "BEGIN:VEVENT" in body:
            parsed = parse_vevent_from_ics(body)
            if parsed:
                return parsed

        if not has_attachments:
            return None

        attachment_infos, _backend = self.list_attachments(item_id)
        for info in attachment_infos:
            name_lower = (info.name or "").lower()
            content_type = (info.content_type or "").lower()
            is_calendar = (
                name_lower.endswith(".ics")
                or "text/calendar" in content_type
                or "application/ics" in content_type
            )
            if not is_calendar:
                continue
            try:
                data, _ = self.get_attachment(item_id, info.attachment_id)
                ics_bytes = base64.b64decode(data.content_base64)
                ics_text = ics_bytes.decode("utf-8", errors="replace")
                parsed = parse_vevent_from_ics(ics_text)
                if parsed:
                    return parsed
            except Exception as exc:
                logger.warning(
                    "Failed to parse calendar attachment %r on %s: %s",
                    info.name,
                    item_id,
                    exc,
                )
        return None

    def stage_email_attachments(
        self,
        item_id: str,
        expires_seconds: Optional[int] = None,
        include_inline: bool = False,
    ) -> tuple[list[dict], str]:
        """Download attachments from EWS, upload to MinIO, return presigned URLs."""
        if not minio_stage.minio_is_configured():
            raise BackendError(
                "MinIO is not configured (MINIO_ENDPOINT, MINIO_ACCESS_KEY, "
                "MINIO_SECRET_KEY, MINIO_BUCKET)",
            )

        attachment_infos, backend = self.list_attachments(item_id)
        staged: list[dict] = []
        ttl = expires_seconds if expires_seconds is not None else settings.minio_presign_ttl_seconds

        for info in attachment_infos:
            if info.is_inline and not include_inline:
                continue
            row = {
                **info.to_dict(),
                "display_name": info.name,
                "presigned_url": "",
            }
            try:
                data, _ = self.get_attachment(item_id, info.attachment_id)
                raw_bytes = base64.b64decode(data.content_base64)
                object_key = minio_stage.build_object_key(item_id, info.name)
                row["presigned_url"] = minio_stage.upload_bytes(
                    raw_bytes,
                    object_key,
                    info.content_type,
                    expires_seconds=ttl,
                )
                row["object_key"] = object_key
            except Exception as exc:
                logger.warning(
                    "Failed to stage attachment %r on %s: %s",
                    info.name,
                    item_id,
                    exc,
                )
                row["error"] = str(exc)
            staged.append(row)

        return staged, backend

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
