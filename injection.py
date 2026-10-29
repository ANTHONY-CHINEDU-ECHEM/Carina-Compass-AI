"""Prompt injection filter for retrieved passages.

Retrieved text is data, never instructions. Passages that try to instruct the
model are dropped before the prompt is built and counted in the metrics, and
the system prompt also marks every source block as untrusted content.
"""

from __future__ import annotations

import re

INJECTION_PATTERNS = [
    re.compile(r"\bignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|prompts|rules)\b", re.I),
    re.compile(r"\bdisregard (all |any )?(the )?(previous|prior|above|system) (instructions|prompt|rules)\b", re.I),
    re.compile(r"\byou are now\b.{0,40}\b(assistant|ai|model|dan|jailbroken)\b", re.I),
    re.compile(r"\b(system prompt|developer message|hidden instructions)\b", re.I),
    re.compile(r"<\|?(im_start|im_end|system|endoftext)\|?>", re.I),
    re.compile(r"\b(reveal|print|output) (your|the) (instructions|system prompt|api key)\b", re.I),
    re.compile(r"\bas an ai (language )?model,? you must\b", re.I),
    re.compile(r"\bnew instructions?:", re.I),
]


def looks_like_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in INJECTION_PATTERNS)
