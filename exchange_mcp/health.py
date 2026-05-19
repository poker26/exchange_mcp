"""Unauthenticated liveness endpoint with EWS reachability check."""
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
    ews_info = health_info.get("ews", {})
    ews_ok = ews_info.get("ok", False)

    if ews_ok:
        status_message = "ok"
    else:
        last_error = ews_info.get("last_error") or "EWS unreachable"
        status_message = f"down: {last_error}"

    return {
        "status": status_message,
        "version": __version__,
        "exchange_host": settings.exchange_host,
        "ews_url": settings.ews_effective_url,
        "backend": "ews",
        "ews": ews_info,
        "state": mail_router.state.snapshot(),
    }
