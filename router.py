"""Provider router with ordered fallbacks and a circuit breaker per vendor.

The selected provider is tried first, then the configured fallbacks, and the
extractive generator always closes the chain. A provider that fails
`failure_threshold` times in a row is skipped for `reset_s` seconds, so a
vendor outage costs one failed call rather than adding latency to every
consultation.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from carina.llm.base import GenerationRequest, GenerationResult, LLMProvider, ProviderError

log = logging.getLogger(__name__)


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    reset_s: float = 60.0
    failures: int = 0
    opened_at: float | None = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if time.monotonic() - self.opened_at >= self.reset_s:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()


@dataclass
class RoutedStream:
    provider: str
    model: str
    fallbacks_used: list[str] = field(default_factory=list)


class ProviderRouter:
    def __init__(self, providers: dict[str, LLMProvider], order: list[str], failure_threshold: int = 3, reset_s: float = 60.0) -> None:
        self.providers = providers
        self.order = [name for name in dict.fromkeys(order + ["extractive"]) if name in providers]
        self.breakers = {name: CircuitBreaker(failure_threshold, reset_s) for name in self.providers}

    def chain(self, preferred: str | None = None) -> list[str]:
        order = list(self.order)
        if preferred and preferred in self.providers:
            order = [preferred] + [n for n in order if n != preferred]
        return order

    def status(self) -> list[dict[str, object]]:
        return [
            {
                "provider": name,
                "model": self.providers[name].model,
                "available": self.providers[name].available(),
                "circuit": self.breakers[name].state,
            }
            for name in self.order
        ]

    async def generate(self, request: GenerationRequest, preferred: str | None = None) -> tuple[GenerationResult, list[str]]:
        skipped: list[str] = []
        for name in self.chain(preferred):
            provider = self.providers[name]
            breaker = self.breakers[name]
            if not breaker.allow() or not provider.available():
                skipped.append(name)
                continue
            try:
                result = await provider.generate(request)
                breaker.record_success()
                return result, skipped
            except ProviderError as exc:
                breaker.record_failure()
                skipped.append(name)
                log.warning("provider failed", extra={"provider": name, "error": str(exc)[:200]})
        raise ProviderError("every provider in the chain failed")

    async def stream(self, request: GenerationRequest, preferred: str | None = None) -> tuple[RoutedStream, AsyncIterator[str]]:
        """Return the provider that accepted the stream and its token iterator.

        A provider is only committed to once it has produced its first token,
        so a failure before any output falls through to the next provider.
        """
        skipped: list[str] = []
        for name in self.chain(preferred):
            provider = self.providers[name]
            breaker = self.breakers[name]
            if not breaker.allow() or not provider.available():
                skipped.append(name)
                continue
            iterator = provider.stream(request).__aiter__()
            try:
                first = await iterator.__anext__()
            except StopAsyncIteration:
                breaker.record_success()
                return RoutedStream(name, provider.model, skipped), _empty()
            except ProviderError as exc:
                breaker.record_failure()
                skipped.append(name)
                log.warning("provider stream failed", extra={"provider": name, "error": str(exc)[:200]})
                continue
            breaker.record_success()
            return RoutedStream(name, provider.model, skipped), _prepend(first, iterator)
        raise ProviderError("every provider in the chain failed")


async def _prepend(first: str, rest: AsyncIterator[str]) -> AsyncIterator[str]:
    yield first
    async for item in rest:
        yield item


async def _empty() -> AsyncIterator[str]:
    if False:  # pragma: no cover
        yield ""
