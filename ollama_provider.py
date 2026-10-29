"""Local inference through Ollama, for deployments where clinical text must stay on site."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from carina.llm.base import GenerationRequest, GenerationResult, ProviderError


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str, base_url: str, timeout_s: float = 120.0) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def available(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=2.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _body(self, request: GenerationRequest, stream: bool) -> dict:  # type: ignore[type-arg]
        return {
            "model": self.model,
            "stream": stream,
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": request.user}],
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
        }

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=self._body(request, False))
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"ollama: {exc}") from exc
        return GenerationResult(
            text=data.get("message", {}).get("content", ""),
            provider=self.name,
            model=self.model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        try:
            async with (
                httpx.AsyncClient(timeout=self.timeout_s) as client,
                client.stream("POST", f"{self.base_url}/api/chat", json=self._body(request, True)) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    piece = data.get("message", {}).get("content")
                    if piece:
                        yield piece
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"ollama stream: {exc}") from exc
