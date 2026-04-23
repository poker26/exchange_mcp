"""EAS driver — thin wrapper around the hardened eas_client.EASClient.

This backend intentionally ignores the server-side SyncKey for the
purpose of cross-channel coherence: the router owns the cursor +
Message-ID LRU, and we just ask EAS for "items since X". Under the
hood EASClient still keeps its own SyncKey state for efficiency, but
if that gets reset (Status=3/12) we surface reset_needed and the
router re-issues the request with a plain filter-based sync.
"""
from __future__ import annotations

import email.utils
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from ..config import settings
from ..eas_client import EASClient
from .base import BackendError, FolderInfo, MailBackend, MailItem

logger = logging.getLogger(__name__)


# EAS FilterType per MS-ASCMD:
#   1=1d, 2=3d, 3=1w, 4=2w, 5=1m, 6=3m, 7=6m
_FILTER_BY_DAYS = [
    (1, "1"),
    (3, "2"),
    (7, "3"),
    (14, "4"),
    (31, "5"),
    (93, "6"),
    (186, "7"),
]


def _filter_for(since: Optional[datetime]) -> str:
    """Pick the smallest FilterType covering the gap between `since` and now."""
    if since is None:
        return "5"  # default: last month
    now = datetime.now(timezone.utc)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    gap = now - since
    days = max(1, int(gap.total_seconds() / 86400) + 1)
    for threshold, code in _FILTER_BY_DAYS:
        if days <= threshold:
            return code
    return "7"  # 6 months, the widest EAS will give us


class EASBackend:
    name = "eas"

    def __init__(self) -> None:
        state_file = os.path.join(settings.state_dir, "eas_internal_state.json")
        self._client = EASClient(
            host=settings.exchange_host,
            username=settings.exchange_user,
            password=settings.exchange_password,
            device_id=settings.eas_device_id,
            protocol_version=settings.eas_protocol,
            email_address=settings.exchange_email,
            state_file=state_file,
        )
        self._folders_cached: Optional[dict] = None

    # --- MailBackend -------------------------------------------------
    def healthcheck(self) -> bool:
        # Issuing FolderSync is the cheapest call that actually proves
        # auth + reachability. Cache the result so repeated health pings
        # don't hammer the server; router calls healthcheck() at most
        # once per minute.
        try:
            folders = self._client.folder_sync()
            if folders:
                self._folders_cached = folders
            return bool(folders)
        except Exception as e:
            logger.debug("EAS healthcheck failed: %s", e)
            return False

    def list_folders(self) -> list[FolderInfo]:
        folders = self._folders_cached or self._client.folder_sync()
        self._folders_cached = folders
        out: list[FolderInfo] = []
        for fid, f in folders.items():
            out.append(FolderInfo(
                id=fid,
                name=f.get("name", ""),
                type=f.get("type"),
                parent=f.get("parent"),
            ))
        return out

    def get_items_since(
        self,
        folder_id: str,
        since: Optional[datetime],
        limit: int = 50,
        include_body: bool = True,
    ) -> list[MailItem]:
        body_size = "51200" if include_body else "0"
        filter_type = _filter_for(since)
        try:
            result = self._client.sync_folder_filtered(
                folder_id,
                filter_type=filter_type,
                window_size=max(1, min(limit, 500)),
                body_type="1",
                body_size=body_size,
            )
        except Exception as e:
            raise BackendError(f"EAS sync failed: {e}") from e

        status = result.get("status")
        if status in (None, "error") or (isinstance(status, str) and status.startswith("HTTP")):
            raise BackendError(f"EAS sync status={status}")

        emails = self._client.parse_emails(result.get("elements", []))
        items: list[MailItem] = []
        for e in emails:
            received = _parse_eas_dt(e.get("date", ""))
            # Drop items older than the cursor — EAS FilterType is coarse.
            if since is not None and received is not None and received <= since:
                continue
            items.append(MailItem(
                backend="eas",
                server_id=e.get("id", "") or "",
                message_id=_message_id_from_headers(e) or _eas_synthetic_mid(e),
                subject=e.get("subject", "") or "",
                sender=e.get("from", "") or "",
                to=e.get("to", "") or "",
                cc=e.get("cc", "") or "",
                received=received,
                read=e.get("read", "0") == "1",
                has_attachments=False,  # EAS attachments require ItemOperations
                preview=e.get("preview", "") or "",
                body=e.get("body", "") or "" if include_body else "",
                body_is_html=False,
            ))
        # Newest first, consistent with EWS.
        items.sort(key=lambda m: m.received or datetime.min.replace(tzinfo=timezone.utc),
                   reverse=True)
        return items[:limit]

    def get_item(self, folder_id: str, server_id: str) -> Optional[MailItem]:
        # Not implemented in v0.1 — EAS single-item fetch needs ItemOperations.
        return None

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: Optional[list[str]] = None,
        body_is_html: bool = False,
    ) -> None:
        raise BackendError("send_email via EAS not implemented in v0.1")


# --- helpers ---------------------------------------------------------
def _parse_eas_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    t = s.replace("-", "").replace(":", "").replace(".000", "")
    if not t.endswith("Z"):
        t += "Z"
    try:
        dt = datetime.strptime(t, "%Y%m%dT%H%M%SZ")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _message_id_from_headers(e: dict) -> str:
    """EAS doesn't expose InternetMessageId directly without MIMESupport.

    Parser in eas_client keeps raw headers under 'internet_headers' when
    MIMESupport is requested; fall back to the 'message_id' field if
    available. If neither — caller synthesizes a stable key.
    """
    raw = e.get("message_id") or ""
    if raw:
        return raw.strip()
    headers = e.get("internet_headers") or ""
    if not headers:
        return ""
    for line in headers.splitlines():
        if line.lower().startswith("message-id:"):
            return line.split(":", 1)[1].strip()
    return ""


def _eas_synthetic_mid(e: dict) -> str:
    """Deterministic dedup key when the real Message-ID isn't available.

    Combines date + from + subject — imperfect but stable across calls
    to the same item. The real fix is to request MIMESupport and parse
    the Message-ID header; that's out of scope for v0.1.
    """
    return f"eas:{e.get('date','')}|{e.get('from','')}|{e.get('subject','')}"
