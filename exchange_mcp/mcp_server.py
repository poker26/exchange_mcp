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
            "Exchange MCP server using EWS (Exchange Web Services) only. "
            "Tools expose folders, mail, calendar, contacts and search. "
            "Incremental mail uses a per-folder cursor and Message-ID LRU "
            "for deduplication."
        ),
    )
    for fn in ALL_TOOLS:
        mcp.tool(fn)
    logger.info("Registered %d tools with FastMCP", len(ALL_TOOLS))
    return mcp


mcp = build_mcp()
