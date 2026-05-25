"""Helpers for Exchange recurring calendar items (EWS / exchangelib)."""
from __future__ import annotations

RECURRENCE_ROLE_SINGLE = "single"
RECURRENCE_ROLE_OCCURRENCE = "occurrence"
RECURRENCE_ROLE_EXCEPTION = "exception"
RECURRENCE_ROLE_SERIES_MASTER = "series_master"


def classify_calendar_recurrence_role(item) -> str:
    """Classify item as single, occurrence, exception, or series_master."""
    raw_type = getattr(item, "type", None)
    type_name = str(raw_type or "").lower().replace("_", "")

    if "recurringmaster" in type_name:
        return RECURRENCE_ROLE_SERIES_MASTER
    if "exception" in type_name:
        return RECURRENCE_ROLE_EXCEPTION
    if "occurrence" in type_name:
        return RECURRENCE_ROLE_OCCURRENCE
    if getattr(item, "recurrence", None) is not None:
        return RECURRENCE_ROLE_SERIES_MASTER
    if getattr(item, "recurring_master_id", None) is not None:
        return RECURRENCE_ROLE_OCCURRENCE
    return RECURRENCE_ROLE_SINGLE


def extract_recurring_master_id(item) -> str:
    master = getattr(item, "recurring_master_id", None)
    if master is None:
        return ""
    return str(getattr(master, "id", master) or "")


def is_series_master_role(role: str) -> bool:
    return role == RECURRENCE_ROLE_SERIES_MASTER


def is_recurring_instance_role(role: str) -> bool:
    return role in (RECURRENCE_ROLE_OCCURRENCE, RECURRENCE_ROLE_EXCEPTION)
