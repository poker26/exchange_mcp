"""Entry point: FastAPI app with FastMCP mounted at /mcp + REST at /api/v1."""
from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .auth import api_key_middleware
from .backends.base import BackendError
from .config import settings
from .health import router as health_router
from .mcp_server import mcp

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("exchange_mcp")


def create_app() -> FastAPI:
    mcp_app = mcp.http_app(path="/")

    app = FastAPI(
        title="Exchange MCP",
        version=__version__,
        description=(
            "Hybrid EWS + EAS MCP server with automatic fallback.\n\n"
            "- `/mcp` — MCP streamable HTTP (send `X-API-Key` or `Authorization: Bearer <key>`).\n"
            "- `/health` — unauthenticated liveness probe with per-channel status.\n"
        ),
        lifespan=mcp_app.lifespan,
    )

    app.add_middleware(BaseHTTPMiddleware, dispatch=api_key_middleware)
    app.include_router(health_router)
    app.mount("/mcp", mcp_app)

    @app.exception_handler(BackendError)
    async def _handle_backend_error(request: Request, exc: BackendError):
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": str(exc)},
        )

    logger.info(
        "exchange-mcp v%s starting on %s:%s, target=%s, preferred=%s",
        __version__,
        settings.server_host,
        settings.server_port,
        settings.exchange_host,
        settings.preferred_backend,
    )
    return app


app = create_app()


def run() -> None:
    uvicorn.run(
        "exchange_mcp.main:app",
        host=settings.server_host,
        port=settings.server_port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    run()
