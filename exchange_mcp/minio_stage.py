"""Upload attachment bytes to MinIO and return presigned GET URLs."""
from __future__ import annotations

import io
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from .config import settings

logger = logging.getLogger(__name__)

_client = None


def minio_is_configured() -> bool:
    return bool(
        settings.minio_endpoint.strip()
        and settings.minio_access_key.strip()
        and settings.minio_secret_key.strip()
        and settings.minio_bucket.strip()
    )


def _parse_endpoint(endpoint: str) -> tuple[str, bool]:
    raw = endpoint.strip()
    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.netloc or parsed.path
        secure = parsed.scheme == "https"
        return host, secure
    secure = settings.minio_secure
    return raw, secure


def _client_or_raise():
    global _client
    if _client is not None:
        return _client
    if not minio_is_configured():
        raise RuntimeError(
            "MinIO is not configured (set MINIO_ENDPOINT, MINIO_ACCESS_KEY, "
            "MINIO_SECRET_KEY, MINIO_BUCKET in .env)",
        )
    from minio import Minio

    host, secure = _parse_endpoint(settings.minio_endpoint)
    _client = Minio(
        host,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=secure,
    )
    return _client


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\-@()+ ]", "_", name or "attachment").strip()
    return cleaned[:180] or "attachment"


def build_object_key(item_id: str, filename: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    item_slug = re.sub(r"[^\w\-]", "_", item_id)[-48:]
    unique = uuid.uuid4().hex[:10]
    return f"exchange-mail/{day}/{item_slug}/{unique}-{_safe_filename(filename)}"


def upload_bytes(
    content: bytes,
    object_name: str,
    content_type: str,
    expires_seconds: Optional[int] = None,
) -> str:
    from datetime import timedelta

    client = _client_or_raise()
    bucket = settings.minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    client.put_object(
        bucket,
        object_name,
        io.BytesIO(content),
        length=len(content),
        content_type=content_type or "application/octet-stream",
    )
    ttl = expires_seconds if expires_seconds is not None else settings.minio_presign_ttl_seconds
    ttl = max(60, min(int(ttl), 604800))
    return client.presigned_get_object(
        bucket,
        object_name,
        expires=timedelta(seconds=ttl),
    )
