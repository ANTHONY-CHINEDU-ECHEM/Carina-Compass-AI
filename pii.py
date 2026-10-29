"""Redaction of patient identifiers before any text leaves the request.

Redaction runs before retrieval, before any model vendor sees the text, before
the cache key is computed and before anything is logged. Placeholders are
typed so the model can still reason ("[AGE] year old") without the identifier.

NHS numbers are only redacted when they pass the modulus 11 check, so a
ten digit lab value or trial number is not mistaken for one, while a valid
number is caught whether it is written with spaces, hyphens or neither.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TITLES = r"(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Professor|Sir|Dame|Lady|Lord)"
NAME_WITH_TITLE = re.compile(rf"\b{TITLES}\.?\s+[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){{0,2}}")
NAME_INTRODUCED = re.compile(r"\b(?:patient(?:'s)? name is|name is|named|called|patient:)\s+([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){0,2})")
NHS_CANDIDATE = re.compile(r"(?<!\d)(\d{3})[\s\-]?(\d{3})[\s\-]?(\d{4})(?!\d)")
POSTCODE = re.compile(r"\b(?:GIR ?0AA|[A-PR-UWYZ][A-HK-Y]?\d[A-Z\d]? ?\d[ABD-HJLNP-UW-Z]{2})\b")
EMAIL = re.compile(r"\b[\w.+\-]+@[\w\-]+\.[\w.\-]+\b")
PHONE = re.compile(r"(?<!\d)(?:\+44\s?\(?0?\)?\s?|0)(?:\d\s?){9,10}(?!\d)")
DOB = re.compile(
    r"\b(?:dob|d\.o\.b\.?|date of birth|born(?: on)?)\s*[:\-]?\s*"
    r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2})",
    re.I,
)
FULL_DATE = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.](?:19|20)\d{2}\b")
HOSPITAL_NUMBER = re.compile(
    r"\b(?:mrn|hospital (?:number|no\.?)|hosp no\.?|unit number|k number|rtx|crn)\s*[:#]?\s*([A-Z]{0,3}\d{5,10}[A-Z]?)\b",
    re.I,
)
ADDRESS = re.compile(r"\b\d{1,4}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Road|Street|Lane|Avenue|Close|Drive|Way|Crescent|Grove|Court|Place|Terrace)\b")


def nhs_number_is_valid(digits: str) -> bool:
    """Validate an NHS number with the modulus 11 algorithm."""
    if len(digits) != 10 or not digits.isdigit() or len(set(digits)) == 1:
        return False
    total = sum(int(d) * w for d, w in zip(digits[:9], range(10, 1, -1), strict=True))
    check = 11 - (total % 11)
    if check == 11:
        check = 0
    if check == 10:
        return False
    return check == int(digits[9])


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def redacted(self) -> bool:
        return bool(self.counts)


def redact(text: str) -> RedactionResult:
    counts: dict[str, int] = {}

    def _sub(pattern: re.Pattern[str], placeholder: str, value: str, group: int | None = None) -> str:
        def repl(match: re.Match[str]) -> str:
            counts[placeholder] = counts.get(placeholder, 0) + 1
            if group is None:
                return f"[{placeholder}]"
            start = match.start(group)
            whole_start = match.start()
            prefix = match.group(0)[: start - whole_start]
            return f"{prefix}[{placeholder}]"

        return pattern.sub(repl, value)

    def _nhs(match: re.Match[str]) -> str:
        digits = "".join(match.groups())
        if nhs_number_is_valid(digits):
            counts["NHS_NUMBER"] = counts.get("NHS_NUMBER", 0) + 1
            return "[NHS_NUMBER]"
        return match.group(0)

    out = EMAIL.sub(lambda m: _count(counts, "EMAIL"), text)
    out = DOB.sub(lambda m: _count(counts, "DATE_OF_BIRTH"), out)
    out = NHS_CANDIDATE.sub(_nhs, out)
    out = _sub(HOSPITAL_NUMBER, "HOSPITAL_NUMBER", out, group=1)
    out = PHONE.sub(lambda m: _count(counts, "PHONE"), out)
    out = FULL_DATE.sub(lambda m: _count(counts, "DATE"), out)
    out = POSTCODE.sub(lambda m: _count(counts, "POSTCODE"), out)
    out = ADDRESS.sub(lambda m: _count(counts, "ADDRESS"), out)
    out = NAME_WITH_TITLE.sub(lambda m: _count(counts, "NAME"), out)
    out = _sub(NAME_INTRODUCED, "NAME", out, group=1)
    return RedactionResult(text=out, counts=counts)


def _count(counts: dict[str, int], placeholder: str) -> str:
    counts[placeholder] = counts.get(placeholder, 0) + 1
    return f"[{placeholder}]"
