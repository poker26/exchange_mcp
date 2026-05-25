from types import SimpleNamespace

from exchange_mcp.calendar_recurrence import (
    RECURRENCE_ROLE_OCCURRENCE,
    RECURRENCE_ROLE_SERIES_MASTER,
    RECURRENCE_ROLE_SINGLE,
    classify_calendar_recurrence_role,
    extract_recurring_master_id,
    is_series_master_role,
)


def test_classify_single_event():
    item = SimpleNamespace(type="Single", recurrence=None, recurring_master_id=None)
    assert classify_calendar_recurrence_role(item) == RECURRENCE_ROLE_SINGLE


def test_classify_series_master_by_recurrence():
    item = SimpleNamespace(type="Single", recurrence={"pattern": "weekly"}, recurring_master_id=None)
    assert classify_calendar_recurrence_role(item) == RECURRENCE_ROLE_SERIES_MASTER


def test_classify_occurrence_by_master_id():
    item = SimpleNamespace(
        type="Occurrence",
        recurrence=None,
        recurring_master_id=SimpleNamespace(id="master-id"),
    )
    assert classify_calendar_recurrence_role(item) == RECURRENCE_ROLE_OCCURRENCE
    assert extract_recurring_master_id(item) == "master-id"


def test_is_series_master_role():
    assert is_series_master_role(RECURRENCE_ROLE_SERIES_MASTER) is True
    assert is_series_master_role(RECURRENCE_ROLE_OCCURRENCE) is False
