"""Unit tests for calendar meeting attendee merge."""
from __future__ import annotations

from exchange_mcp.calendar_meeting import merge_attendee_lists, normalize_smtp_address


class FakeAttendee:
    def __init__(self, email: str) -> None:
        self.mailbox = type("Mailbox", (), {"email_address": email})()


def test_normalize_smtp_prefix() -> None:
    assert normalize_smtp_address("SMTP:user@example.com") == "user@example.com"


def test_merge_attendee_lists_add_and_remove() -> None:
    existing = [FakeAttendee("a@corp.ru"), FakeAttendee("b@corp.ru")]

    def create_attendee(email: str) -> FakeAttendee:
        return FakeAttendee(email)

    merged, added, removed = merge_attendee_lists(
        existing,
        ["c@corp.ru"],
        ["b@corp.ru"],
        create_attendee=create_attendee,
    )
    emails = [getattr(item.mailbox, "email_address") for item in merged]
    assert emails == ["a@corp.ru", "c@corp.ru"]
    assert added == ["c@corp.ru"]
    assert removed == ["b@corp.ru"]
