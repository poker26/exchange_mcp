"""Unauthenticated liveness endpoint exposing both channels' status."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from . import __version__
from .clients import router as mail_router
from .config import settings

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", tags=["meta"])
async def health() -> dict:
    health_info = mail_router.health_snapshot()
    ews_ok = health_info.get("ews", {}).get("ok", False)
    eas_ok = health_info.get("eas", {}).get("ok", False)

    if ews_ok and eas_ok:
        status_msg = "ok"
    elif ews_ok or eas_ok:
        parts = []
        if not ews_ok:
            parts.append("ews: " + (health_info["ews"].get("last_error") or "down"))
        if not eas_ok:
            parts.append("eas: " + (health_info["eas"].get("last_error") or "down"))
        status_msg = "degraded: " + " | ".join(parts)
    else:
        status_msg = "down: both channels unreachable"

    return {
        "status": status_msg,
        "version": __version__,
        "exchange_host": settings.exchange_host,
        "preferred": health_info.get("preferred"),
        "channels": {
            "ews": health_info.get("ews", {}),
            "eas": health_info.get("eas", {}),
        },
        "state": mail_router.state.snapshot(),
    }
