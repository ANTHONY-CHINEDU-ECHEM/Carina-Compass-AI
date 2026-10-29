"""Polite HTTP harvesting shared by every connector.

Rate limiting with a token bucket per host (PubMed allows 3 requests a
second without a key and 10 with one; ClinicalTrials.gov about 50 a minute).
Retries with exponential backoff and jitter on 429, 5xx and network errors,
honouring Retry After.
robots.txt is checked before any HTML page is fetched.
An identifying User Agent with a contact address, as NCBI and NLM request.
"""

from __future__ import annotations

import logging
import random
import threading
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

import httpx

from carina import __version__
from carina.domain import Document

log = logging.getLogger(__name__)

USER_AGENT = f"CarinaCompassAI/{__version__} (clinical evidence indexer; mailto:maintainers@carina-compass.example)"


class RateLimiter:
    def __init__(self, rate_per_s: float, burst: int = 1) -> None:
        self.rate = rate_per_s
        self.capacity = burst
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


class HttpClient:
    def __init__(self, rate_per_s: float = 2.0, timeout_s: float = 45.0, max_retries: int = 5) -> None:
        self.limiter = RateLimiter(rate_per_s)
        self.max_retries = max_retries
        self.client = httpx.Client(timeout=timeout_s, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def allowed_by_robots(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._robots.get(base)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser()
            try:
                response = self.client.get(f"{base}/robots.txt")
                parser.parse(response.text.splitlines() if response.status_code == 200 else [])
            except httpx.HTTPError:
                parser.parse([])
            self._robots[base] = parser
        return parser.can_fetch(USER_AGENT, url)

    def request(self, method: str, url: str, *, check_robots: bool = False, **kwargs: Any) -> httpx.Response:
        if check_robots and not self.allowed_by_robots(url):
            raise PermissionError(f"robots.txt disallows {url}")
        delay = 1.0
        for attempt in range(self.max_retries + 1):
            self.limiter.acquire()
            try:
                response = self.client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                if attempt == self.max_retries:
                    raise
                log.warning("network error, retrying", extra={"url": url, "attempt": attempt, "error": str(exc)})
            else:
                if response.status_code < 400:
                    return response
                if response.status_code not in (429, 500, 502, 503, 504) or attempt == self.max_retries:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, float(retry_after))
            time.sleep(delay + random.uniform(0, delay / 2))
            delay = min(delay * 2, 60)
        raise RuntimeError("unreachable")

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs).json()

    def get_text(self, url: str, **kwargs: Any) -> str:
        return self.request("GET", url, **kwargs).text

    def close(self) -> None:
        self.client.close()


class Source(ABC):
    """A connector yields cleaned, graded and tagged Documents."""

    name: str = "source"

    def __init__(self, config: dict[str, Any], client: HttpClient | None = None) -> None:
        self.config = config
        self.client = client or HttpClient(rate_per_s=float(config.get("rate_per_s", 2.0)))

    @abstractmethod
    def harvest(self, limit: int | None = None) -> Iterator[Document]:
        """Yield documents, stopping after `limit` if given."""

    def enabled(self) -> bool:
        return bool(self.config.get("enabled", True))
