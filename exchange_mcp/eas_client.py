"""
EAS Client Library for Exchange ActiveSync
Handles WBXML encoding/decoding and EAS protocol commands.
"""

import io
import json
import logging
import os
import threading
import time
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ============================================================
# WBXML Code Pages (verified against Exchange 2019)
# ============================================================

CP_AIRSYNC = {
    0x05: "Sync", 0x06: "Responses", 0x07: "Add",
    0x08: "Change", 0x09: "Delete", 0x0A: "Fetch",
    0x0B: "SyncKey", 0x0C: "ClientId", 0x0D: "ServerId",
    0x0E: "Status", 0x0F: "Collection", 0x10: "Class",
    0x11: "Version", 0x12: "CollectionId", 0x13: "GetChanges",
    0x14: "MoreAvailable", 0x15: "WindowSize", 0x16: "Commands",
    0x17: "Options", 0x18: "FilterType", 0x1B: "Conflict",
    0x1C: "Collections", 0x1D: "ApplicationData",
    0x1E: "DeletesAsMoves", 0x22: "MIMESupport",
}

CP_CONTACTS = {
    0x05: "Anniversary", 0x06: "AssistantName",
    0x07: "AssistantPhoneNumber", 0x08: "Birthday",
    0x09: "Body", 0x0A: "BodySize", 0x0B: "BodyTruncated",
    0x0C: "Business2PhoneNumber", 0x0D: "BusinessCity",
    0x0E: "BusinessCountry", 0x0F: "BusinessPostalCode",
    0x10: "BusinessState", 0x11: "BusinessStreet",
    0x12: "BusinessFaxNumber", 0x13: "BusinessPhoneNumber",
    0x14: "CarPhoneNumber", 0x15: "Categories",
    0x16: "Category", 0x17: "Children", 0x18: "Child",
    0x19: "CompanyName", 0x1A: "Department",
    0x1B: "Email1Address", 0x1C: "Email2Address",
    0x1D: "Email3Address", 0x1E: "FileAs",
    0x1F: "FirstName", 0x20: "Home2PhoneNumber",
    0x21: "HomeCity", 0x22: "HomeCountry",
    0x23: "HomePostalCode", 0x24: "HomeState",
    0x25: "HomeStreet", 0x26: "HomeFaxNumber",
    0x27: "HomePhoneNumber", 0x28: "JobTitle",
    0x29: "LastName", 0x2A: "MiddleName",
    0x2B: "MobilePhoneNumber", 0x2C: "OfficeLocation",
    0x33: "RadioPhoneNumber", 0x34: "Spouse",
    0x35: "Suffix", 0x36: "Title", 0x37: "WebPage",
}

CP_EMAIL = {
    0x05: "Attachment", 0x06: "Attachments", 0x07: "AttName",
    0x08: "AttSize", 0x0C: "Body", 0x0D: "BodySize",
    0x0E: "BodyTruncated", 0x0F: "DateReceived",
    0x10: "DisplayName", 0x11: "DisplayTo", 0x12: "Importance",
    0x13: "MessageClass", 0x14: "Subject", 0x15: "Read",
    0x16: "To", 0x17: "Cc", 0x18: "From", 0x19: "ReplyTo",
    0x1A: "AllDayEvent", 0x1D: "DtStamp", 0x1E: "EndTime",
    0x20: "BusyStatus", 0x21: "Location",
    0x23: "Organizer", 0x31: "StartTime",
    0x35: "ThreadTopic", 0x38: "MIMESize",
    0x39: "InternetCPID", 0x3C: "Flag", 0x3D: "FlagStatus",
}

CP_CALENDAR = {
    0x05: "TimeZone", 0x06: "AllDayEvent", 0x07: "Attendees",
    0x08: "Attendee", 0x09: "Attendee_Email",
    0x0A: "Attendee_Name", 0x0B: "Body", 0x0C: "BodyTruncated",
    0x0D: "BusyStatus", 0x0E: "Categories", 0x0F: "Category",
    0x11: "DtStamp", 0x12: "EndTime",
    0x13: "Exception", 0x14: "Exceptions",
    0x15: "Exception_Deleted", 0x16: "Exception_StartTime",
    0x17: "Location", 0x18: "MeetingStatus",
    0x19: "Organizer_Email", 0x1A: "Organizer_Name",
    0x1B: "Recurrence", 0x1C: "Recurrence_Type",
    0x1D: "Recurrence_Until", 0x1E: "Recurrence_Occurrences",
    0x1F: "Recurrence_Interval", 0x20: "Recurrence_DayOfWeek",
    0x21: "Recurrence_DayOfMonth", 0x22: "Recurrence_WeekOfMonth",
    0x23: "Recurrence_MonthOfYear",
    0x24: "Reminder", 0x25: "Sensitivity", 0x26: "Subject",
    0x27: "StartTime", 0x28: "UID",
    0x29: "Attendee_Status", 0x2A: "Attendee_Type",
}

CP_FOLDER = {
    0x07: "DisplayName", 0x08: "ServerId", 0x09: "ParentId",
    0x0A: "Type", 0x0C: "Status", 0x0E: "Changes",
    0x0F: "Add", 0x10: "Delete", 0x11: "Update",
    0x12: "SyncKey", 0x16: "FolderSync", 0x17: "Count",
}

CP_AIRSYNCBASE = {
    0x05: "BodyPreference", 0x06: "Type", 0x07: "TruncationSize",
    0x0A: "Body", 0x0B: "Data", 0x0C: "EstimatedDataSize",
    0x0D: "Truncated", 0x0E: "Attachments", 0x0F: "Attachment",
    0x10: "DisplayName", 0x11: "FileReference",
    0x12: "Method", 0x15: "IsInline",
    0x16: "NativeBodyType", 0x17: "ContentType",
    0x19: "Preview",
}

# Page 14: ItemOperations
CP_ITEMOPS = {
    0x05: "ItemOperations", 0x06: "Fetch", 0x07: "Store",
    0x08: "Options", 0x09: "Range", 0x0A: "Total",
    0x0B: "Properties", 0x0C: "Data", 0x0D: "Status",
    0x0E: "Response", 0x0F: "Version", 0x10: "Schema",
    0x11: "Part", 0x12: "EmptyFolderContents",
    0x13: "DeleteSubFolders",
}

ALL_PAGES = {
    0: CP_AIRSYNC, 1: CP_CONTACTS, 2: CP_EMAIL,
    4: CP_CALENDAR, 7: CP_FOLDER, 14: CP_ITEMOPS, 17: CP_AIRSYNCBASE,
}

FOLDER_TYPES = {
    1: "Generic", 2: "Inbox", 3: "Drafts", 4: "Deleted",
    5: "Sent", 6: "Outbox", 7: "Tasks", 8: "Calendar",
    9: "Contacts", 10: "Notes", 11: "Journal",
    12: "User Mail", 13: "User Calendar", 14: "User Contacts",
    15: "User Tasks", 17: "User Notes", 19: "Recipient Cache",
}


# ============================================================
# WBXML Encoder
# ============================================================
class WBXMLEncoder:
    def __init__(self):
        self.buf = bytearray(b'\x03\x01\x6a\x00')
        self.page = 0

    def switch(self, page):
        if page != self.page:
            self.buf.extend([0x00, page])
            self.page = page

    def tag_open(self, page, tag):
        self.switch(page)
        self.buf.append(tag | 0x40)

    def tag_empty(self, page, tag):
        self.switch(page)
        self.buf.append(tag)

    def end(self):
        self.buf.append(0x01)

    def string(self, s):
        self.buf.append(0x03)
        self.buf.extend(s.encode('utf-8'))
        self.buf.append(0x00)

    def tag_str(self, page, tag, value):
        self.tag_open(page, tag)
        self.string(value)
        self.end()

    def get(self):
        return bytes(self.buf)


# ============================================================
# WBXML Decoder
# ============================================================
class WBXMLDecoder:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.page = 0

    def _rb(self):
        if self.pos >= len(self.data):
            return None
        b = self.data[self.pos]
        self.pos += 1
        return b

    def _rmb(self):
        r = 0
        while self.pos < len(self.data):
            b = self.data[self.pos]
            self.pos += 1
            r = (r << 7) | (b & 0x7F)
            if not (b & 0x80):
                return r
        return r

    def _rstr(self):
        c = []
        while self.pos < len(self.data):
            b = self.data[self.pos]
            self.pos += 1
            if b == 0:
                break
            c.append(b)
        return bytes(c).decode('utf-8', errors='replace')

    def decode(self):
        self._rb()
        self._rmb()
        self._rmb()
        stl = self._rmb()
        self.pos += stl
        result = []
        self._parse(result, 0)
        return result

    def _parse(self, result, depth):
        while self.pos < len(self.data):
            t = self._rb()
            if t is None or t == 0x01:
                return
            if t == 0x00:
                self.page = self._rb()
                continue
            if t == 0x03:
                s = self._rstr()
                if result and result[-1][2] is None:
                    result[-1] = (result[-1][0], result[-1][1], s)
                continue
            if t == 0xC3:
                ln = self._rmb()
                self.pos += ln
                continue
            hc = bool(t & 0x40)
            tid = t & 0x3F
            cp = ALL_PAGES.get(self.page, {})
            name = cp.get(tid, f"p{self.page}:0x{tid:02X}")
            result.append((depth, name, None))
            if hc:
                self._parse(result, depth + 1)


# ============================================================
# EAS Client
# ============================================================
class EASClient:
    def __init__(self, host: str, username: str, password: str,
                 device_id: str = "EAS0LEGCLIENT0001",
                 device_type: str = "EASClient",
                 protocol_version: str = "14.1",
                 email_address: str = "",
                 state_file: str = ""):
        self.host = host
        self.url = f"https://{host}/Microsoft-Server-ActiveSync"
        self.username = username
        self.email_address = email_address or username
        self.device_id = device_id
        self.device_type = device_type
        self.protocol_version = protocol_version
        self.client = httpx.Client(
            auth=(username, password),
            verify=False,
            timeout=30.0,
        )
        self.folders: dict = {}
        self.sync_keys: dict = {}
        self.incr_keys: dict = {}
        self.state_file = state_file or ""
        # Serializes HTTP calls and multi-step sync sequences so concurrent
        # MCP requests don't race on SyncKey / state file.
        self._lock = threading.RLock()
        if self.state_file:
            self._load_state()

    def close(self):
        self.client.close()

    # Retry on transient failures: EAS spec lists 449 (Retry-After) and 503 as
    # retryable; we also retry 504 and httpx network/timeout errors. Without
    # this, a single blip makes Sync return HTTP-wrapped "error" and the
    # caller treats it as "no new mail".
    _RETRY_STATUSES = (449, 503, 504, 507)
    _RETRY_DELAYS = (2.0, 4.0, 8.0)

    def _post(self, cmd: str, wbxml: bytes) -> httpx.Response:
        with self._lock:
            last_exc: Optional[Exception] = None
            for attempt in range(len(self._RETRY_DELAYS) + 1):
                try:
                    resp = self.client.post(
                        self.url,
                        params={"Cmd": cmd, "User": self.username,
                                "DeviceId": self.device_id,
                                "DeviceType": self.device_type},
                        headers={"MS-ASProtocolVersion": self.protocol_version,
                                 "Content-Type": "application/vnd.ms-sync.wbxml"},
                        content=wbxml,
                    )
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_exc = e
                    if attempt >= len(self._RETRY_DELAYS):
                        raise
                    wait = self._RETRY_DELAYS[attempt]
                    logger.warning("EAS %s transport error: %s, retry in %.0fs",
                                   cmd, e, wait)
                    time.sleep(wait)
                    continue

                if resp.status_code in self._RETRY_STATUSES and attempt < len(self._RETRY_DELAYS):
                    wait = self._RETRY_DELAYS[attempt]
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait = max(wait, float(retry_after))
                        except ValueError:
                            pass
                    logger.warning("EAS %s HTTP %d, retry in %.0fs",
                                   cmd, resp.status_code, wait)
                    time.sleep(wait)
                    continue
                return resp
            # All retries exhausted on transport errors with no response
            raise RuntimeError(f"EAS {cmd} failed after retries") from last_exc

    def _decode(self, resp: httpx.Response) -> list:
        if resp.status_code == 200 and resp.content:
            return WBXMLDecoder(resp.content).decode()
        return []

    def _find(self, elements: list, tag_name: str) -> Optional[str]:
        for _, tag, val in elements:
            if tag == tag_name and val is not None:
                return val
        return None

    # --- State persistence ---
    def _load_state(self):
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                self.sync_keys = state.get("sync_keys", {})
                self.incr_keys = state.get("incr_keys", {})
                logger.info("Loaded state: %d sync keys", len(self.sync_keys))
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("No existing state file, starting fresh")

    def _save_state(self):
        if not self.state_file:
            return
        # Atomic write: a crash mid-write leaves the old file intact
        # instead of corrupting state with a partial JSON.
        tmp = self.state_file + ".tmp"
        try:
            with open(tmp, 'w') as f:
                json.dump({"sync_keys": self.sync_keys, "incr_keys": self.incr_keys}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.state_file)
        except Exception as e:
            logger.error("Failed to save state: %s", e)
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # --- Incremental sync ---
    def sync_incremental(self, collection_id: str, window_size: int = 50,
                         body_type: str = "1", body_size: str = "51200") -> dict:
        """Sync only new/changed items since last sync.

        Uses stored SyncKey. On first call, drains all existing items
        (without returning them) to establish baseline. Subsequent calls
        return only new items.

        On Status=3/12 (server-side SyncKey reset) returns
        status="reset_needed" and clears the stored key. The caller is
        expected to bridge the gap via its own cursor (e.g. timestamp +
        Message-ID dedup) — blindly re-draining here loses any items
        that arrived between the reset and the next successful sync.

        Returns dict with status, sync_key, elements, is_initial.
        """
        with self._lock:
            stored_key = self.incr_keys.get(str(collection_id))

            if not stored_key:
                # First time: drain all existing items to establish baseline
                logger.info("Initial sync for folder %s — draining existing items", collection_id)
                r1 = self.sync(collection_id, "0")
                key = r1.get("sync_key")
                if not key:
                    return {"status": "error", "elements": [], "is_initial": True}

                # Drain loop: keep syncing until no more items
                total_drained = 0
                while True:
                    r = self.sync(collection_id, key, window_size=500,
                                 body_type="1", body_size="0")
                    new_key = r.get("sync_key")
                    status = r.get("status")

                    if status == "no_changes" or not r.get("elements"):
                        # Fully drained
                        if new_key:
                            key = new_key
                        break

                    count = len([e for e in r.get("elements", []) if e[1] == "ServerId" and e[2]])
                    total_drained += count
                    if new_key:
                        key = new_key

                    if count == 0:
                        break

                self.incr_keys[str(collection_id)] = key
                self._save_state()
                logger.info("Initial sync done for folder %s: drained %d items, key=%s",
                           collection_id, total_drained, key)

                return {
                    "status": "initial_sync_done",
                    "sync_key": key,
                    "elements": [],
                    "is_initial": True,
                    "drained": total_drained,
                }

            # Incremental: use stored key — only new items
            r = self.sync(collection_id, stored_key, window_size=window_size,
                         body_type=body_type, body_size=body_size)

            new_key = r.get("sync_key")
            status = r.get("status")

            # Invalid SyncKey on server — drop stored key and tell the caller
            # to recover via its own cursor. Do NOT re-drain automatically:
            # if the drain is interrupted we lose whatever arrived between
            # the reset and the next sync.
            if status in ("3", "12"):
                logger.warning(
                    "SyncKey invalid for folder %s (status=%s); dropping stored key, "
                    "caller must bridge the gap via its own cursor",
                    collection_id, status,
                )
                self.incr_keys.pop(str(collection_id), None)
                self._save_state()
                return {
                    "status": "reset_needed",
                    "sync_key": None,
                    "elements": [],
                    "is_initial": False,
                }

            if status == "no_changes":
                return {"status": "no_changes", "sync_key": stored_key,
                        "elements": [], "is_initial": False}

            if new_key:
                self.incr_keys[str(collection_id)] = new_key
                self._save_state()

            return {
                "status": status,
                "sync_key": new_key,
                "elements": r.get("elements", []),
                "is_initial": False,
            }

    # --- FolderSync ---
    def folder_sync(self) -> dict:
        enc = WBXMLEncoder()
        enc.tag_open(7, 0x16)
        enc.tag_str(7, 0x12, "0")
        enc.end()

        resp = self._post("FolderSync", enc.get())
        elements = self._decode(resp)

        if self._find(elements, "Status") != "1":
            logger.error("FolderSync failed: %s", self._find(elements, "Status"))
            return {}

        folders = {}
        cur = {}
        for _, tag, value in elements:
            if tag == "DisplayName" and value:
                cur["name"] = value
            elif tag == "ServerId" and value:
                cur["id"] = value
            elif tag == "Type" and value:
                cur["type"] = int(value)
            elif tag == "ParentId" and value:
                cur["parent"] = value
            elif tag == "Add" and value is None:
                if cur.get("id"):
                    folders[cur["id"]] = cur
                cur = {}
        if cur.get("id"):
            folders[cur["id"]] = cur

        self.folders = folders
        return folders

    def find_folder(self, folder_type: int) -> Optional[str]:
        for fid, f in self.folders.items():
            if f.get("type") == folder_type:
                return fid
        return None

    # --- Sync ---
    def sync(self, collection_id: str, sync_key: str = "0",
             window_size: int = 50, body_type: str = "1",
             body_size: str = "51200", filter_type: str = "") -> dict:
        enc = WBXMLEncoder()
        enc.tag_open(0, 0x05)   # Sync
        enc.tag_open(0, 0x1C)   # Collections
        enc.tag_open(0, 0x0F)   # Collection
        enc.tag_str(0, 0x0B, sync_key)
        enc.tag_str(0, 0x12, str(collection_id))

        if sync_key != "0":
            enc.tag_empty(0, 0x13)  # GetChanges
            enc.tag_str(0, 0x15, str(window_size))
            enc.tag_open(0, 0x17)   # Options
            if filter_type:
                enc.tag_str(0, 0x18, filter_type)  # FilterType
            enc.tag_open(17, 0x05)  # BodyPreference
            enc.tag_str(17, 0x06, body_type)
            enc.tag_str(17, 0x07, body_size)
            enc.end()  # BodyPreference
            enc.end()  # Options

        enc.end()  # Collection
        enc.end()  # Collections
        enc.end()  # Sync

        resp = self._post("Sync", enc.get())

        if resp.status_code != 200:
            return {"status": f"HTTP {resp.status_code}", "items": []}
        if not resp.content:
            return {"status": "no_changes", "items": [], "sync_key": sync_key}

        elements = self._decode(resp)
        status = self._find(elements, "Status")
        new_key = self._find(elements, "SyncKey")

        if new_key:
            self.sync_keys[collection_id] = new_key

        return {"status": status, "sync_key": new_key, "elements": elements}

    def sync_folder(self, collection_id: str, **kwargs) -> dict:
        """Full sync: fetches ALL items by looping until Exchange has no more."""
        with self._lock:
            r1 = self.sync(collection_id, "0")
            key = r1.get("sync_key")
            if not key:
                return r1

            all_elements = []
            max_rounds = 50  # safety limit
            for _ in range(max_rounds):
                r = self.sync(collection_id, key, **kwargs)
                new_key = r.get("sync_key")
                elements = r.get("elements", [])
                status = r.get("status")

                # Count actual items (ServerId tags = items)
                item_count = sum(1 for _, tag, val in elements if tag == "ServerId" and val)

                if elements:
                    all_elements.extend(elements)

                if new_key and new_key != key:
                    key = new_key
                else:
                    break  # key didn't change = nothing more

                if status == "no_changes" or item_count == 0:
                    break

                logger.info("sync_folder loop: got %d items, continuing...", item_count)

            logger.info("sync_folder complete: %d total elements",
                        sum(1 for _, tag, val in all_elements if tag == "ServerId" and val))

            return {
                "status": "1",
                "sync_key": key,
                "elements": all_elements,
            }

    def sync_folder_filtered(self, collection_id: str, filter_type: str = "5", **kwargs) -> dict:
        """Sync with date filter. filter_type: 4=2weeks, 5=1month, 6=3months, 7=6months"""
        with self._lock:
            r1 = self.sync(collection_id, "0", filter_type=filter_type)
            key = r1.get("sync_key")
            if not key:
                return r1
            return self.sync(collection_id, key, filter_type=filter_type, **kwargs)

    # --- Parsers ---
    def parse_emails(self, elements: list) -> list:
        emails = []
        cur = {}
        for _, tag, value in elements:
            if tag == "ServerId" and value:
                if cur.get("subject") or cur.get("from"):
                    emails.append(cur)
                cur = {"server_id": value}
                continue
            if value is not None:
                mapping = {
                    "Subject": "subject", "From": "from", "To": "to",
                    "Cc": "cc", "DateReceived": "date",
                    "DisplayTo": "display_to", "Importance": "importance",
                    "Read": "read", "MessageClass": "class",
                    "Data": "body", "Preview": "preview",
                    "EstimatedDataSize": "size", "ThreadTopic": "thread_topic",
                    "FileReference": "file_reference",
                    "DisplayName": "att_display_name",
                    "AttName": "att_name",
                }
                if tag in mapping:
                    cur[mapping[tag]] = value
        if cur.get("subject") or cur.get("from"):
            emails.append(cur)
        return emails

    def parse_calendar(self, elements: list) -> list:
        events = []
        cur = {}
        for _, tag, value in elements:
            if tag == "ServerId" and value:
                if cur.get("subject") or cur.get("start"):
                    events.append(cur)
                cur = {"server_id": value}
                continue
            if value is None:
                continue
            mapping = {
                "Subject": "subject", "StartTime": "start",
                "EndTime": "end", "Location": "location",
                "Organizer_Name": "organizer_name",
                "Organizer_Email": "organizer_email",
                "AllDayEvent": "all_day", "BusyStatus": "busy_status",
                "Reminder": "reminder", "UID": "uid", "DtStamp": "stamp",
                "MeetingStatus": "meeting_status",
                "Recurrence_Type": "recurrence_type",
                "Recurrence_Interval": "recurrence_interval",
                "Recurrence_DayOfWeek": "recurrence_dayofweek",
                "Recurrence_DayOfMonth": "recurrence_dayofmonth",
                "Recurrence_WeekOfMonth": "recurrence_weekofmonth",
                "Recurrence_MonthOfYear": "recurrence_monthofyear",
                "Recurrence_Until": "recurrence_until",
                "Recurrence_Occurrences": "recurrence_occurrences",
            }
            if tag == "Attendee_Name":
                cur.setdefault("attendees", []).append({"name": value})
            elif tag == "Attendee_Email":
                att = cur.get("attendees", [])
                if att:
                    att[-1]["email"] = value
            elif tag in mapping:
                cur[mapping[tag]] = value
        if cur.get("subject") or cur.get("start"):
            events.append(cur)
        return events

    def expand_recurring(self, events: list, date_from: str, date_to: str) -> list:
        """Expand recurring events into individual instances for a date range.
        
        Args:
            events: list from parse_calendar
            date_from: YYYYMMDD
            date_to: YYYYMMDD
            
        Returns:
            list of events with recurring ones expanded into instances
        """
        from datetime import timedelta

        def parse_dt(s):
            if not s:
                return None
            s = s.replace("-", "").replace(":", "").replace(".000", "")
            if not s.endswith("Z"):
                s += "Z"
            try:
                return datetime.strptime(s, "%Y%m%dT%H%M%SZ")
            except ValueError:
                return None

        range_start = datetime.strptime(date_from, "%Y%m%d")
        range_end = datetime.strptime(date_to, "%Y%m%d") + timedelta(days=1)

        result = []

        for ev in events:
            start_dt = parse_dt(ev.get("start"))
            end_dt = parse_dt(ev.get("end"))

            if not start_dt:
                result.append(ev)
                continue

            rec_type = ev.get("recurrence_type")
            if rec_type is None:
                # Non-recurring: include if in range
                if start_dt.strftime("%Y%m%d") >= date_from and start_dt.strftime("%Y%m%d") <= date_to:
                    result.append(ev)
                continue

            # Recurring event - expand
            try:
                rec_type = int(rec_type)
            except (ValueError, TypeError):
                result.append(ev)
                continue

            interval = int(ev.get("recurrence_interval", "1") or "1")
            dow = int(ev.get("recurrence_dayofweek", "0") or "0")
            dom = int(ev.get("recurrence_dayofmonth", "0") or "0")
            until_dt = parse_dt(ev.get("recurrence_until"))
            max_occ = int(ev.get("recurrence_occurrences", "0") or "0")
            duration = (end_dt - start_dt) if end_dt else timedelta(hours=1)

            # Effective end
            eff_end = range_end
            if until_dt and until_dt < eff_end:
                eff_end = until_dt

            occ_count = 0
            max_iterations = 1000  # safety

            if rec_type == 0:
                # Daily
                cur = start_dt
                for _ in range(max_iterations):
                    if cur >= eff_end:
                        break
                    if max_occ and occ_count >= max_occ:
                        break
                    if cur.strftime("%Y%m%d") >= date_from and cur.strftime("%Y%m%d") <= date_to:
                        instance = ev.copy()
                        instance["start"] = cur.strftime("%Y%m%dT%H%M%SZ")
                        instance["end"] = (cur + duration).strftime("%Y%m%dT%H%M%SZ")
                        instance["is_recurring_instance"] = True
                        result.append(instance)
                    occ_count += 1
                    cur += timedelta(days=interval)

            elif rec_type == 1:
                # Weekly (dow is bitmask: 1=Sun,2=Mon,4=Tue,8=Wed,16=Thu,32=Fri,64=Sat)
                day_map = {0: 2, 1: 4, 2: 8, 3: 16, 4: 32, 5: 64, 6: 1}  # python weekday -> EAS
                # If dow==0, use the day of the original start
                if dow == 0:
                    dow = day_map.get(start_dt.weekday(), 0)
                
                cur = start_dt
                week_count = 0
                last_week = -1
                for _ in range(max_iterations):
                    if cur >= eff_end:
                        break
                    if max_occ and occ_count >= max_occ:
                        break
                    
                    # Check week interval
                    weeks_since = (cur - start_dt).days // 7
                    if interval > 1 and weeks_since % interval != 0:
                        cur += timedelta(days=1)
                        continue
                    
                    py_wd = cur.weekday()
                    eas_wd = day_map.get(py_wd, 0)
                    
                    if dow & eas_wd:
                        if cur.strftime("%Y%m%d") >= date_from and cur.strftime("%Y%m%d") <= date_to:
                            instance = ev.copy()
                            t = start_dt.strftime("%H%M%S")
                            instance["start"] = cur.strftime(f"%Y%m%dT{t}Z")
                            instance["end"] = (cur + duration).strftime(f"%Y%m%dT") + (start_dt + duration).strftime("%H%M%SZ")
                            instance["is_recurring_instance"] = True
                            result.append(instance)
                        occ_count += 1
                    
                    cur += timedelta(days=1)

            elif rec_type == 2:
                # Monthly (specific day of month)
                if dom == 0:
                    dom = start_dt.day
                cur_year = start_dt.year
                cur_month = start_dt.month
                for _ in range(max_iterations):
                    if max_occ and occ_count >= max_occ:
                        break
                    try:
                        cur = start_dt.replace(year=cur_year, month=cur_month, day=dom)
                    except ValueError:
                        # Day doesn't exist in this month (e.g. Feb 30)
                        cur_month += interval
                        if cur_month > 12:
                            cur_year += cur_month // 12
                            cur_month = cur_month % 12 or 12
                        continue
                    
                    if cur >= eff_end:
                        break
                    
                    if cur.strftime("%Y%m%d") >= date_from and cur.strftime("%Y%m%d") <= date_to:
                        instance = ev.copy()
                        t = start_dt.strftime("%H%M%S")
                        instance["start"] = cur.strftime(f"%Y%m%dT{t}Z")
                        instance["end"] = (cur + duration).strftime(f"%Y%m%dT") + (start_dt + duration).strftime("%H%M%SZ")
                        instance["is_recurring_instance"] = True
                        result.append(instance)
                    occ_count += 1
                    
                    cur_month += interval
                    if cur_month > 12:
                        cur_year += (cur_month - 1) // 12
                        cur_month = (cur_month - 1) % 12 + 1

            elif rec_type == 5:
                # Yearly (specific month and day)
                moy = int(ev.get("recurrence_monthofyear", "0") or "0") or start_dt.month
                if dom == 0:
                    dom = start_dt.day
                cur_year = start_dt.year
                for _ in range(max_iterations):
                    if max_occ and occ_count >= max_occ:
                        break
                    try:
                        cur = start_dt.replace(year=cur_year, month=moy, day=dom)
                    except ValueError:
                        cur_year += interval
                        continue
                    if cur >= eff_end:
                        break
                    if cur.strftime("%Y%m%d") >= date_from and cur.strftime("%Y%m%d") <= date_to:
                        instance = ev.copy()
                        t = start_dt.strftime("%H%M%S")
                        instance["start"] = cur.strftime(f"%Y%m%dT{t}Z")
                        instance["end"] = (cur + duration).strftime(f"%Y%m%dT") + (start_dt + duration).strftime("%H%M%SZ")
                        instance["is_recurring_instance"] = True
                        result.append(instance)
                    occ_count += 1
                    cur_year += interval

            else:
                # Unknown type - include as-is if in range
                if start_dt.strftime("%Y%m%d") >= date_from and start_dt.strftime("%Y%m%d") <= date_to:
                    result.append(ev)

        result.sort(key=lambda e: e.get("start", ""))
        return result

    def parse_contacts(self, elements: list) -> list:
        contacts = []
        cur = {}
        fields = {
            "FileAs", "FirstName", "LastName", "MiddleName",
            "CompanyName", "Department", "JobTitle",
            "Email1Address", "Email2Address", "Email3Address",
            "BusinessPhoneNumber", "MobilePhoneNumber",
            "HomePhoneNumber", "BusinessCity", "BusinessStreet",
        }
        for _, tag, value in elements:
            if tag == "ServerId" and value:
                if cur.get("FileAs") or cur.get("FirstName"):
                    contacts.append(cur)
                cur = {"server_id": value}
                continue
            if value is not None and tag in fields:
                cur[tag] = value
        if cur.get("FileAs") or cur.get("FirstName"):
            contacts.append(cur)
        return contacts

    # --- Get Attachment ---
    def get_attachment(self, file_reference: str) -> dict:
        """Download an attachment by FileReference.

        Args:
            file_reference: The FileReference from email attachment metadata

        Returns:
            dict with 'data' (base64), 'content_type', 'status'
        """
        import base64 as b64module

        enc = WBXMLEncoder()
        # <ItemOperations> page 14, tag 0x05
        enc.tag_open(14, 0x05)
        # <Fetch> tag 0x06
        enc.tag_open(14, 0x06)
        # <Store> tag 0x07
        enc.tag_str(14, 0x07, "Mailbox")
        # <FileReference> - AirSyncBase page 17, tag 0x11
        enc.tag_str(17, 0x11, file_reference)
        enc.end()  # Fetch
        enc.end()  # ItemOperations

        resp = self._post("ItemOperations", enc.get())

        if resp.status_code == 200 and resp.content:
            elements = self._decode(resp)
            status = self._find(elements, "Status")
            data = None
            content_type = None
            for _, tag, val in elements:
                if tag == "Data" and val:
                    data = val
                if tag == "ContentType" and val:
                    content_type = val

            if status == "1" and data:
                return {
                    "status": "ok",
                    "data": data,
                    "content_type": content_type,
                    "file_reference": file_reference,
                }
            return {"status": f"error_{status}"}
        return {"status": f"HTTP {resp.status_code}"}

    # --- SendMail ---
    def send_email(self, to: str, subject: str, body: str,
                   cc: str = "", content_type: str = "plain") -> dict:
        """Send an email via EAS SendMail command.
        
        Args:
            to: Recipient email (comma-separated for multiple)
            subject: Email subject
            body: Email body text
            cc: CC recipients (optional)
            content_type: 'plain' or 'html'
        
        Returns:
            dict with status
        """
        # Build MIME message
        msg = MIMEText(body, content_type, "utf-8")
        msg["From"] = self.email_address
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg["Date"] = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
        msg["Message-ID"] = f"<{uuid.uuid4()}@eas-mcp>"

        mime_data = msg.as_bytes()

        # SendMail uses raw MIME, not WBXML
        # But needs a small WBXML wrapper with ClientId
        client_id = str(uuid.uuid4())[:8]

        # Build SendMail WBXML
        enc = WBXMLEncoder()
        # Page 21: ComposeMail
        enc.switch(21)
        # <SendMail> tag 0x05 with content
        enc.buf.append(0x05 | 0x40)
        # <ClientId> tag 0x11
        enc.buf.append(0x11 | 0x40)
        enc.string(client_id)
        enc.end()
        # <SaveInSentItems/> tag 0x08
        enc.buf.append(0x08)
        # <Mime> tag 0x10 with content (opaque data)
        enc.buf.append(0x10 | 0x40)
        # Write opaque: token 0xC3 + mb_uint32 length + data
        enc.buf.append(0xC3)
        # Encode length as mb_uint32
        length = len(mime_data)
        length_bytes = []
        while True:
            length_bytes.insert(0, length & 0x7F)
            length >>= 7
            if length == 0:
                break
        for i in range(len(length_bytes) - 1):
            length_bytes[i] |= 0x80
        enc.buf.extend(length_bytes)
        enc.buf.extend(mime_data)
        enc.end()  # Mime
        enc.end()  # SendMail

        resp = self._post("SendMail", enc.get())

        if resp.status_code == 200:
            # Empty 200 = success for SendMail
            if not resp.content:
                return {"status": "sent", "to": to, "subject": subject}
            # Non-empty = error in WBXML
            elements = self._decode(resp)
            status = self._find(elements, "Status")
            return {"status": f"error_{status}", "elements": elements}
        else:
            return {"status": f"HTTP {resp.status_code}"}

    # --- Create Calendar Event ---
    def create_event(self, subject: str, start_time: str, end_time: str,
                     location: str = "", body: str = "",
                     attendees: list = None, all_day: bool = False,
                     reminder: int = 15) -> dict:
        """Create a calendar event via EAS Sync Add command.
        
        Args:
            subject: Event title
            start_time: ISO format e.g. '2026-03-25T10:00:00Z' or '20260325T100000Z'
            end_time: ISO format e.g. '2026-03-25T11:00:00Z' or '20260325T110000Z'
            location: Event location (optional)
            body: Event description (optional)
            attendees: List of dicts [{"email": "...", "name": "..."}] (optional)
            all_day: Whether it is an all-day event
            reminder: Reminder in minutes (default 15)
        
        Returns:
            dict with status and server_id
        """
        cal_id = self.find_folder(8)
        if not cal_id:
            return {"status": "error", "message": "Calendar folder not found"}

        # Convert ISO dates to EAS compact format: 20260325T100000Z
        def to_eas_date(s):
            s = s.replace("-", "").replace(":", "").replace(".000", "")
            if not s.endswith("Z"):
                s += "Z"
            return s

        eas_start = to_eas_date(start_time)
        eas_end = to_eas_date(end_time)
        eas_stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

        # UTC timezone blob (all zeros = UTC)
        # This is a 172-byte base64-encoded TIME_ZONE_INFORMATION structure
        import base64
        utc_tz = base64.b64encode(b"\x00" * 172).decode()

        # Step 1: get sync key
        r1 = self.sync(cal_id, "0")
        sync_key = r1.get("sync_key")
        if not sync_key:
            return {"status": "error", "message": "Failed to get SyncKey"}

        # Step 2: full sync to advance key
        r2 = self.sync(cal_id, sync_key, window_size=1)
        sync_key2 = r2.get("sync_key") or sync_key

        client_id = str(uuid.uuid4())[:8]

        enc = WBXMLEncoder()
        enc.tag_open(0, 0x05)   # Sync
        enc.tag_open(0, 0x1C)   # Collections
        enc.tag_open(0, 0x0F)   # Collection
        enc.tag_str(0, 0x0B, sync_key2)
        enc.tag_str(0, 0x12, str(cal_id))
        enc.tag_open(0, 0x16)   # Commands
        enc.tag_open(0, 0x07)   # Add
        enc.tag_str(0, 0x0C, client_id)
        enc.tag_open(0, 0x1D)   # ApplicationData

        # Calendar fields - page 4
        enc.tag_str(4, 0x05, utc_tz)        # TimeZone (required!)
        enc.tag_str(4, 0x06, "1" if all_day else "0")  # AllDayEvent
        enc.tag_str(4, 0x0D, "2")           # BusyStatus = Busy
        enc.tag_str(4, 0x11, eas_stamp)     # DtStamp
        enc.tag_str(4, 0x12, eas_end)       # EndTime
        enc.tag_str(4, 0x25, "0")           # Sensitivity = Normal
        enc.tag_str(4, 0x26, subject)       # Subject
        enc.tag_str(4, 0x27, eas_start)     # StartTime
        enc.tag_str(4, 0x28, str(uuid.uuid4()))  # UID
        enc.tag_str(4, 0x18, "1" if attendees else "0")  # MeetingStatus
        enc.tag_str(4, 0x24, str(reminder)) # Reminder

        if location:
            enc.tag_str(4, 0x17, location)

        # Body - AirSyncBase page 17
        if body:
            enc.tag_open(17, 0x0A)  # Body
            enc.tag_str(17, 0x06, "1")  # Type = plain text
            enc.tag_str(17, 0x0B, body)  # Data
            enc.end()

        # Attendees
        if attendees:
            enc.tag_open(4, 0x07)  # Attendees
            for att in attendees:
                enc.tag_open(4, 0x08)  # Attendee
                enc.tag_str(4, 0x09, att.get("email", ""))
                enc.tag_str(4, 0x0A, att.get("name", att.get("email", "")))
                enc.tag_str(4, 0x2A, "1")  # Type = Required
                enc.tag_str(4, 0x29, "0")  # Status = None
                enc.end()
            enc.end()

        enc.end()  # ApplicationData
        enc.end()  # Add
        enc.end()  # Commands
        enc.end()  # Collection
        enc.end()  # Collections
        enc.end()  # Sync

        resp = self._post("Sync", enc.get())

        if resp.status_code == 200 and resp.content:
            elements = self._decode(resp)
            status = self._find(elements, "Status")
            server_id = None
            # Find ServerId in Responses section
            in_responses = False
            for _, tag, val in elements:
                if tag == "Responses":
                    in_responses = True
                if in_responses and tag == "Status" and val:
                    status = val
                if in_responses and tag == "ServerId" and val:
                    server_id = val

            if status == "1":
                return {"status": "created", "server_id": server_id, "client_id": client_id}
            else:
                return {"status": f"error_{status}", "client_id": client_id}
        elif resp.status_code == 200:
            return {"status": "created_empty_response", "client_id": client_id}
        else:
            return {"status": f"HTTP {resp.status_code}"}
