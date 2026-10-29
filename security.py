"""API key authentication and a per key sliding window rate limit."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque

from fastapi import Depends, Header, HTTPException, Request, status

from carina.config import Settings, get_settings


def _matches(candidate: str, keys: list[str]) -> bool:
    return any(hmac.compare_digest(candidate, key) for key in keys)


def require_api_key(x_api_key: str | None = Header(default=None), settings: Settings = Depends(get_settings)) -> str:
    """Development runs without keys; once CC_API_KEYS is set every request needs one."""
    if not settings.api_keys:
        return "anonymous"
    if not x_api_key or not _matches(x_api_key, settings.api_keys + settings.admin_api_keys):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "A valid X-API-Key header is required")
    return x_api_key


def require_admin(x_api_key: str | None = Header(default=None), settings: Settings = Depends(get_settings)) -> str:
    if not settings.admin_api_keys:
        if settings.environment == "production":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin keys are not configured")
        return "anonymous-admin"
    if not x_api_key or not _matches(x_api_key, settings.admin_api_keys):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "An admin API key is required")
    return x_api_key


class RateLimiter:
    def __init__(self) -> None:
        self.windows: dict[str, deque[float]] = defaultdict(deque)

    def __call__(self, request: Request, key: str = Depends(require_api_key), settings: Settings = Depends(get_settings)) -> None:
        identity = key if key != "anonymous" else (request.client.host if request.client else "unknown")
        now = time.monotonic()
        window = self.windows[identity]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= settings.rate_limit_per_minute:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded", headers={"Retry-After": "60"})
        window.append(now)


rate_limit = RateLimiter()
