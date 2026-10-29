"""Guideline currency: recognise withdrawn or replaced editions of guidance."""

from __future__ import annotations

import re
from functools import lru_cache

from carina.domain import Chunk
from carina.knowledge import load

REFERENCE = re.compile(r"\b(TA\d{2,4}|NG\d{2,4}|CG\d{2,4}|TNM\s?[89])\b", re.I)


@lru_cache(maxsize=1)
def replaced_by() -> dict[str, str]:
    return {edge["old"].upper(): edge["new"].upper() for edge in load("supersession.yaml")["edges"]}


@lru_cache(maxsize=1)
def notes() -> dict[str, str]:
    return {edge["old"].upper(): edge["note"] for edge in load("supersession.yaml")["edges"]}


def primary_reference(chunk: Chunk) -> str | None:
    for key in ("nice", "guidance", "edition"):
        value = chunk.identifiers.get(key)
        if value:
            return value.upper().replace(" ", "")
    match = REFERENCE.search(chunk.title)
    return match.group(1).upper().replace(" ", "") if match else None


def superseding(chunk: Chunk) -> str | None:
    """Return the reference that replaces this chunk's guidance, if any."""
    if chunk.superseded_by:
        return chunk.superseded_by
    ref = primary_reference(chunk)
    if not ref:
        return None
    return replaced_by().get(ref)
