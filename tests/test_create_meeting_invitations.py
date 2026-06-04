"""Unit tests for create-event meeting invitation defaults."""
from __future__ import annotations

from exchange_mcp.backends.ews import EWSBackend


def test_create_send_to_all_when_attendees_present() -> None:
    mode, alias, expect = EWSBackend._resolve_create_send_meeting_invitations(
        ["a@corp.ru"],
        "to_all",
    )
    assert alias == "to_all"
    assert expect is True
    assert mode == "SendToAllAndSaveCopy"


def test_create_save_only_skips_invitations() -> None:
    mode, alias, expect = EWSBackend._resolve_create_send_meeting_invitations(
        ["a@corp.ru"],
        "save_only",
    )
    assert alias == "save_only"
    assert expect is False
    assert mode == "SendToNone"


def test_create_no_attendees_is_personal() -> None:
    mode, alias, expect = EWSBackend._resolve_create_send_meeting_invitations(
        [],
        "to_all",
    )
    assert expect is False
    assert mode == "SendToNone"
