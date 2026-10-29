"""Claude through the Anthropic Messages API.

The system prompt is sent as a cacheable block, so repeat consultations reuse
the cached prefix and cost less and respond faster.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from carina.llm.base import GenerationRequest, GenerationResult, ProviderError


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, timeout_s: float = 60.0) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self._client = None

    def available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def _get_client(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise ProviderError("anthropic package not installed") from exc
            self._client = anthropic.AsyncAnthropic(timeout=self.timeout_s, max_retries=2)
        return self._client

    def _payload(self, request: GenerationRequest) -> dict:  # type: ignore[type-arg]
        return {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": request.user}],
        }

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        client = self._get_client()
        try:
            response = await client.messages.create(**self._payload(request))
        except Exception as exc:
            raise ProviderError(f"anthropic: {exc}") from exc
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        usage = response.usage
        return GenerationResult(
            text=text,
            provider=self.name,
            model=self.model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        client = self._get_client()
        try:
            async with client.messages.stream(**self._payload(request)) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as exc:
            raise ProviderError(f"anthropic stream: {exc}") from exc
