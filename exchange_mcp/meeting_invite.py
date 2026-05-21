"""Parse meeting times from iCalendar (VEVENT) text in mail invites."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional


_ICAL_UNESC = {
    "\\n": "\n",
    "\\,": ",",
    "\\;": ";",
    "\\\\": "\\",
}


def _unescape_ical(value: str) -> str:
    text = value.strip()
    for escaped, plain in _ICAL_UNESC.items():
        text = text.replace(escaped, plain)
    return text


def _parse_ical_datetime(raw: str) -> Optional[datetime]:
    value = raw.strip()
    if not value:
        return None

    if re.fullmatch(r"\d{8}T\d{6}Z", value):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)

    if re.fullmatch(r"\d{8}T\d{6}", value):
        return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)

    if re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _folded_ics_lines(text: str) -> list[str]:
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    unfolded: list[str] = []
    for line in raw_lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def parse_vevent_from_ics(ics_text: str) -> Optional[dict]:
    """Return meeting start/end/location/summary from the first VEVENT block."""
    if not ics_text or "BEGIN:VEVENT" not in ics_text:
        return None

    in_event = False
    fields: dict[str, str] = {}
    for line in _folded_ics_lines(ics_text):
        if line == "BEGIN:VEVENT":
            in_event = True
            fields = {}
            continue
        if line == "END:VEVENT":
            if fields.get("DTSTART"):
                start = _parse_ical_datetime(fields["DTSTART"])
                if start is None:
                    return None
                end_raw = fields.get("DTEND") or fields.get("DTSTART")
                end = _parse_ical_datetime(end_raw) if end_raw else None
                return {
                    "start": start.isoformat(),
                    "end": end.isoformat() if end else "",
                    "location": _unescape_ical(fields.get("LOCATION", "")),
                    "summary": _unescape_ical(fields.get("SUMMARY", "")),
                }
            in_event = False
            continue
        if not in_event or ":" not in line:
            continue
        key_part, value = line.split(":", 1)
        key = key_part.split(";", 1)[0].upper()
        if key in ("DTSTART", "DTEND", "LOCATION", "SUMMARY"):
            fields[key] = value.strip()

    return None


def looks_like_meeting_invite(subject: str, body: str, has_attachments: bool) -> bool:
    haystack = f"{subject}\n{body}".lower()
    if "begin:vevent" in haystack:
        return True
    markers = (
        "telemost.yandex",
        "zoom.us",
        "meet.google",
        "teams.microsoft",
        "приглашение",
        "invitation",
        "meeting request",
        "calendar",
    )
    if any(marker in haystack for marker in markers):
        return True
    return has_attachments and any(
        token in haystack for token in ("встреч", "meeting", "собран", "демо")
    )
