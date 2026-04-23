"""FastMCP setup: register every tool from `exchange_mcp.tools`."""
from __future__ import annotations

import logging

from fastmcp import FastMCP

from .tools import ALL_TOOLS

logger = logging.getLogger(__name__)


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        name="exchange-mcp",
        instructions=(
            "Exchange MCP server with hybrid EWS+EAS backend and automatic "
            "fallback. Tools expose folders, mail, calendar, contacts and "
            "search. Each call is routed to the healthier channel; state "
            "(per-folder cursor + Message-ID LRU) is shared so clients "
            "never see duplicates or gaps across channel switches."
        ),
    )
    for fn in ALL_TOOLS:
        mcp.tool(fn)
    logger.info("Registered %d tools with FastMCP", len(ALL_TOOLS))
    return mcp


mcp = build_mcp()
