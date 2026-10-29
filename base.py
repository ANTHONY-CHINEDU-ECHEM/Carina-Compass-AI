"""Provider interface shared by Anthropic, OpenAI, Ollama and the extractive generator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class GenerationRequest:
    system: str
    user: str
    max_tokens: int = 1400
    temperature: float = 0.1
    # Retrieved passages, used only by the extractive generator.
    passages: list[tuple[int, str]] = field(default_factory=list)
    passage_weights: dict[int, float] = field(default_factory=dict)
    query: str = ""
    setting: str | None = None
    biomarkers: list[str] = field(default_factory=list)
    drugs: list[str] = field(default_factory=list)
    superseded: dict[int, str] = field(default_factory=dict)
    titles: dict[int, str] = field(default_factory=dict)
    pdl1_tps: float | None = None


@dataclass
class GenerationResult:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0


class ProviderError(RuntimeError):
    """Raised when a provider call fails and the router should try the next one."""


class LLMProvider(Protocol):
    name: str
    model: str

    def available(self) -> bool: ...

    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]: ...
