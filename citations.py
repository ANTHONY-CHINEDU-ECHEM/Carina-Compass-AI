"""Citation validation and clinical figure checking.

After generation, every citation is checked against the ids actually supplied,
invalid ones are stripped, sentence level coverage is measured, and every
number carrying a clinical unit (mg, mg/m2, AUC, Gy, fractions, %, months,
hazard ratios) must appear in at least one passage the sentence cites.
Unsupported figures are flagged to the clinician inside the answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CITATION = re.compile(r"\[(\d{1,2})\]")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])|\n+")
FIGURE = re.compile(
    r"(?:(?:hr|hazard ratio|auc)\s*(?:of|=)?\s*)?"
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*"
    r"(%|mg/m2|mg/m²|mg/kg|mg|micrograms?|ml/min|gy|fractions?|months?|weeks?|years?|cycles?|mm|cm)?",
    re.I,
)
CLINICAL_UNIT = {"%", "mg/m2", "mg/m²", "mg/kg", "mg", "microgram", "micrograms", "ml/min", "gy", "fraction", "fractions", "month", "months", "cycle", "cycles"}
NON_FACTUAL_PREFIXES = ("clinical judgement", "note:", "caution:")


@dataclass
class CitationReport:
    text: str
    cited_ids: list[int]
    invalid_ids: list[int]
    sentence_count: int
    cited_sentence_count: int
    coverage: float
    unsupported_figures: list[str] = field(default_factory=list)

    @property
    def figures_ok(self) -> bool:
        return not self.unsupported_figures

    def as_dict(self) -> dict[str, object]:
        return {
            "cited_ids": self.cited_ids,
            "invalid_ids": self.invalid_ids,
            "sentence_count": self.sentence_count,
            "cited_sentence_count": self.cited_sentence_count,
            "coverage": round(self.coverage, 3),
            "unsupported_figures": self.unsupported_figures,
        }


def split_answer_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE.split(text) if s and s.strip()]


def is_factual(sentence: str) -> bool:
    stripped = sentence.strip().lower().lstrip("-*• ")
    if not stripped or stripped.startswith(NON_FACTUAL_PREFIXES):
        return False
    return len(re.findall(r"[a-z]{3,}", stripped)) >= 4


def _normalise_number(value: str) -> str:
    return value.rstrip("0").rstrip(".") if "." in value else value


def clinical_figures(sentence: str) -> list[tuple[str, str]]:
    figures = []
    for match in FIGURE.finditer(sentence):
        number, unit = match.group(1), (match.group(2) or "").lower()
        prefix = match.group(0).lower()
        is_ratio = prefix.startswith(("hr", "hazard", "auc"))
        if unit in CLINICAL_UNIT or is_ratio:
            figures.append((_normalise_number(number), unit))
    return figures


NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?")


def _figure_in_text(number: str, text: str) -> bool:
    """Numeric comparison, so 0.5 matches 0.50 and 24 matches 24.0."""
    try:
        target = float(number)
    except ValueError:
        return False
    return any(abs(float(found) - target) < 1e-9 for found in NUMBER.findall(text))


def validate(answer: str, sources: dict[int, str]) -> CitationReport:
    """Strip invalid citations, measure coverage and check clinical figures."""
    invalid: list[int] = []

    def _fix(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if idx in sources:
            return match.group(0)
        invalid.append(idx)
        return ""

    cleaned = CITATION.sub(_fix, answer)
    cleaned = re.sub(r"\s+([.,;])", r"\1", cleaned)
    sentences = [s for s in split_answer_sentences(cleaned) if is_factual(s)]
    cited_ids: set[int] = set()
    cited_sentences = 0
    unsupported: list[str] = []
    for sentence in sentences:
        ids = [int(i) for i in CITATION.findall(sentence)]
        if ids:
            cited_sentences += 1
            cited_ids.update(ids)
        evidence = " ".join(sources.get(i, "") for i in ids)
        for number, unit in clinical_figures(sentence):
            if not ids or not _figure_in_text(number, evidence):
                label = f"{number}{(' ' + unit) if unit and unit != '%' else unit}"
                if label not in unsupported:
                    unsupported.append(label)
    coverage = cited_sentences / len(sentences) if sentences else 0.0
    return CitationReport(
        text=cleaned,
        cited_ids=sorted(cited_ids),
        invalid_ids=sorted(set(invalid)),
        sentence_count=len(sentences),
        cited_sentence_count=cited_sentences,
        coverage=coverage,
        unsupported_figures=unsupported,
    )


def flag_unsupported(text: str, unsupported: list[str]) -> str:
    if not unsupported:
        return text
    note = "\n\nFigure check: the following figures could not be found in the cited sources and must be verified before use: " + ", ".join(unsupported) + "."
    return text + note
