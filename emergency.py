"""Oncology emergency triage, run before retrieval.

A match produces an action banner that is streamed as the first event of the
response, so the clinician sees what to do immediately even if retrieval or
the model is slow or unavailable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from carina.knowledge import load


@dataclass(frozen=True)
class EmergencyAlert:
    category: str
    title: str
    actions: tuple[str, ...]
    guidance: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"category": self.category, "title": self.title, "actions": list(self.actions), "guidance": list(self.guidance)}

    def retrieval_hint(self) -> str:
        return f"{self.title} " + " ".join(self.guidance)


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, dict[str, Any], list[re.Pattern[str]]]]:
    data = load("emergencies.yaml")
    rules = []
    for category, spec in data["categories"].items():
        patterns = [re.compile(p, re.I | re.S) for p in spec["patterns"]]
        rules.append((category, spec, patterns))
    return rules


_NEGATION = re.compile(r"\b(no|not|without|denies|negative for|ruled out)\s+(\w+\s+){0,3}$", re.I)


def triage(text: str) -> list[EmergencyAlert]:
    alerts: list[EmergencyAlert] = []
    for category, spec, patterns in _compiled():
        for pattern in patterns:
            match = pattern.search(text)
            if match and not _NEGATION.search(text[max(0, match.start() - 40) : match.start()]):
                alerts.append(
                    EmergencyAlert(
                        category=category,
                        title=spec["title"],
                        actions=tuple(spec["actions"]),
                        guidance=tuple(spec.get("guidance", [])),
                    )
                )
                break
    return alerts
