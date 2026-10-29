"""Evaluation metrics for retrieval, grounding, safety and routing."""

from __future__ import annotations

from typing import Any


def hit_at_k(retrieved: list[str], expected: list[str], k: int = 5) -> float | None:
    if not expected:
        return None
    head = retrieved[:k]
    return 1.0 if any(any(r.startswith(e) for e in expected) for r in head) else 0.0


def reciprocal_rank(retrieved: list[str], expected: list[str]) -> float | None:
    if not expected:
        return None
    for rank, chunk_id in enumerate(retrieved, start=1):
        if any(chunk_id.startswith(e) for e in expected):
            return 1.0 / rank
    return 0.0


def fact_recall(answer: str, facts: list[str]) -> float | None:
    if not facts:
        return None
    lowered = answer.lower()
    return sum(1 for fact in facts if fact.lower() in lowered) / len(facts)


def tool_routing(tools: list[dict[str, Any]], expected: list[str]) -> float:
    fired = {t["tool"] for t in tools}
    if not expected:
        return 1.0
    return 1.0 if set(expected) <= fired else 0.0


def mean(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 3) if clean else None
