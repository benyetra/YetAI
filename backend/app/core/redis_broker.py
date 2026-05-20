"""Redis broker URL helpers for Celery and admin diagnostics."""

from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse


def pick_redis_url() -> str:
    """Resolve broker URL from env (Railway plugin may set several names)."""
    for key in (
        "REDIS_URL",
        "REDIS_PRIVATE_URL",
        "REDIS_PUBLIC_URL",
        "CELERY_BROKER_URL",
    ):
        value = (os.getenv(key) or "").strip()
        if value and "localhost" not in value:
            return normalize_redis_url(value)
    from app.core.config import settings

    return normalize_redis_url(settings.REDIS_URL)


def normalize_redis_url(url: str) -> str:
    """Celery/kombu sometimes log redis://host:6379// — normalize to db 0."""
    url = (url or "").strip()
    if not url:
        return url
    if url.endswith("//"):
        return url[:-1] + "0"
    if url.endswith("/"):
        return url + "0"
    return url


def mask_redis_target(url: str) -> str:
    """Host:port for logs (no credentials)."""
    parsed = urlparse(normalize_redis_url(url))
    host = parsed.hostname or "unknown"
    port = parsed.port or 6379
    return f"{host}:{port}"


def ping_redis_sync(url: str, *, timeout_s: float = 5.0) -> dict:
    """Blocking PING from the current process (API or worker startup)."""
    import redis

    target = mask_redis_target(url)
    try:
        client = redis.from_url(
            normalize_redis_url(url),
            socket_connect_timeout=timeout_s,
            socket_timeout=timeout_s,
        )
        client.ping()
        return {"status": "ok", "target": target}
    except Exception as exc:
        return {"status": "error", "target": target, "error": str(exc)}
