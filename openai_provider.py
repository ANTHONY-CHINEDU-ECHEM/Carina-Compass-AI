"""OpenAI Chat Completions provider."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from carina.llm.base import GenerationRequest, GenerationResult, ProviderError


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str, timeout_s: float = 60.0) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self._client = None

    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def _get_client(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover
                raise ProviderError("openai package not installed") from exc
            self._client = openai.AsyncOpenAI(timeout=self.timeout_s, max_retries=2)
        return self._client

    def _messages(self, request: GenerationRequest) -> list[dict[str, str]]:
        return [{"role": "system", "content": request.system}, {"role": "user", "content": request.user}]

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        client = self._get_client()
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=self._messages(request),
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
        except Exception as exc:
            raise ProviderError(f"openai: {exc}") from exc
        usage = response.usage
        return GenerationResult(
            text=response.choices[0].message.content or "",
            provider=self.name,
            model=self.model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        client = self._get_client()
        try:
            stream = await client.chat.completions.create(
                model=self.model,
                messages=self._messages(request),
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                stream=True,
            )
            async for event in stream:
                delta = event.choices[0].delta.content if event.choices else None
                if delta:
                    yield delta
        except Exception as exc:
            raise ProviderError(f"openai stream: {exc}") from exc
