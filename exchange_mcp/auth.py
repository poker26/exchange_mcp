"""X-API-Key / Bearer auth. Middleware guards /mcp/*, Depends guards REST."""
from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from .config import settings


def _check_key(provided: Optional[str]) -> None:
    if not provided or provided != settings.mcp_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """FastAPI dependency for REST endpoints."""
    _check_key(x_api_key)


def _bearer_token(authz: Optional[str]) -> Optional[str]:
    if not authz:
        return None
    prefix, _, token = authz.partition(" ")
    return token if prefix.lower() == "bearer" else None


# Paths exempt from the /mcp middleware gate.
_PUBLIC_PREFIXES = ("/health", "/docs", "/openapi.json", "/redoc")


async def api_key_middleware(request: Request, call_next: RequestResponseEndpoint):
    path = request.url.path
    if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await call_next(request)

    if path.startswith("/mcp"):
        key = request.headers.get("x-api-key") or _bearer_token(
            request.headers.get("authorization")
        )
        if not key or key != settings.mcp_api_key:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing API key"},
            )

    return await call_next(request)
