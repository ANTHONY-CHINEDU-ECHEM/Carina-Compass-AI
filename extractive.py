"""Extractive generator: the last provider in the fallback chain.

When no model vendor is configured or reachable, the answer is assembled from
the retrieved passages themselves. Sentences are scored against the question
(IDF weighted, with extra weight for biomarkers, drugs and numbers), the best
ones are kept with diversity across sources, and each carries the citation of
the passage it came from. Every figure is therefore verbatim from a source.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable

from carina.clinical.understanding import BIOMARKER_PATTERNS, SETTING_PATTERNS
from carina.generation.prompts import CLOSING_LINE
from carina.llm.base import GenerationRequest, GenerationResult
from carina.retrieval.hybrid import setting_group
from carina.retrieval.reranker import DECISIVE
from carina.retrieval.tokenizer import tokenize

RESULTS_QUESTION = re.compile(r"\b(evidence|results?|show\w*|survival|response|benefit|efficacy|achiev\w*|outcomes?|data)\b", re.I)
RESULT_FIGURE = re.compile(r"\d+(?:\.\d+)?\s?(%|months)|hazard ratio", re.I)
PDL1_THRESHOLD = re.compile(r"(?:pd-l1|tumour proportion score)[^.]{0,80}?at least (\d{1,3})%", re.I)
SENTENCE_SPLIT = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_SPLIT.split(text.strip()) if p.strip()]
    return [p if p.endswith((".", ";")) else p + "." for p in parts]


class ExtractiveGenerator:
    name = "extractive"
    model = "extractive-v2"

    def __init__(self, idf: Callable[[str], float] | None = None, max_sentences: int = 6) -> None:
        self.idf = idf or (lambda _t: 1.0)
        self.max_sentences = max_sentences

    def available(self) -> bool:
        return True

    def compose(
        self,
        query: str,
        passages: list[tuple[int, str]],
        weights: dict[int, float] | None = None,
        setting: str | None = None,
        biomarkers: list[str] | None = None,
        pdl1_tps: float | None = None,
        drugs: list[str] | None = None,
        superseded: dict[int, str] | None = None,
        titles: dict[int, str] | None = None,
    ) -> str:
        superseded = superseded or {}
        titles = titles or {}
        wants_results = bool(RESULTS_QUESTION.search(query))
        named = {sid for sid, title in titles.items() if _names_trial(query, title)}
        weights = weights or {}
        wanted_group = setting_group(setting)
        wanted_markers = set(biomarkers or [])
        q_terms = set(tokenize(query))
        if not q_terms or not passages:
            return "INSUFFICIENT_EVIDENCE"
        candidates: list[tuple[float, int, int, str]] = []
        for rank, (source_id, text) in enumerate(passages):
            for position, sentence in enumerate(split_sentences(text)):
                s_terms = set(tokenize(sentence))
                if len(s_terms) < 4:
                    continue
                overlap = q_terms & s_terms
                minimum = 1 if source_id in named else 2
                if len(overlap) < minimum and not any(DECISIVE.match(t) for t in overlap):
                    continue
                weight = sum(self.idf(t) * (2.0 if DECISIVE.match(t) else 1.0) for t in overlap)
                weight *= 1.0 / (1 + 0.08 * rank)  # earlier passages ranked higher by retrieval
                weight *= 1.0 / (1 + 0.03 * position)  # leading sentences carry the main finding
                weight *= weights.get(source_id, 1.0)  # stronger evidence first
                if _is_registry_boilerplate(sentence):
                    weight *= 0.3
                if wanted_group:
                    groups = {setting_group(code) for code, pattern in SETTING_PATTERNS if pattern.search(sentence)} - {None}
                    if groups and wanted_group not in groups:
                        weight *= 0.2
                if wanted_markers:
                    markers = {code for code, pattern in BIOMARKER_PATTERNS if pattern.search(sentence)}
                    if markers and not markers & wanted_markers:
                        weight *= 0.2
                    elif not markers:
                        weight *= 0.45
                elif pdl1_tps is not None and any(p.search(sentence) for _, p in BIOMARKER_PATTERNS):
                    # A PD L1 driven question implies a driver negative tumour.
                    weight *= 0.4
                if drugs:
                    lowered = sentence.lower()
                    context = f"{titles.get(source_id, '')} {text}".lower()
                    if any(drug in lowered for drug in drugs):
                        weight *= 1.8
                    elif any(drug in context for drug in drugs):
                        weight *= 1.3
                    else:
                        weight *= 0.5
                if named:
                    weight *= 2.0 if source_id in named else 0.5
                if wants_results and RESULT_FIGURE.search(sentence):
                    weight *= 1.6
                if pdl1_tps is not None:
                    threshold = PDL1_THRESHOLD.search(sentence)
                    if threshold and float(threshold.group(1)) > pdl1_tps:
                        weight *= 0.2
                candidates.append((weight, source_id, position, sentence))
        if not candidates:
            return "INSUFFICIENT_EVIDENCE"
        candidates.sort(key=lambda c: c[0], reverse=True)
        chosen: list[tuple[int, int, str]] = []
        per_source: dict[int, int] = {}
        best = candidates[0][0]
        for weight, source_id, position, sentence in candidates:
            if weight < best * 0.3:
                break
            if per_source.get(source_id, 0) >= 2:
                continue
            if any(_similar(sentence, existing) for _, _, existing in chosen):
                continue
            per_source[source_id] = per_source.get(source_id, 0) + 1
            chosen.append((source_id, position, sentence))
            if len(chosen) >= self.max_sentences:
                break
        lines = []
        for source_id, _, sentence in chosen:
            note = f" (this guidance has been replaced by {superseded[source_id]})" if source_id in superseded else ""
            lines.append(f"{sentence.rstrip('.;')}{note} [{source_id}].")
        return " ".join(lines) + "\n\n" + CLOSING_LINE

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        text = self.compose(
            request.query,
            request.passages,
            request.passage_weights,
            request.setting,
            request.biomarkers,
            request.pdl1_tps,
            request.drugs,
            request.superseded,
            request.titles,
        )
        return GenerationResult(text=text, provider=self.name, model=self.model)

    async def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        text = self.compose(
            request.query,
            request.passages,
            request.passage_weights,
            request.setting,
            request.biomarkers,
            request.pdl1_tps,
            request.drugs,
            request.superseded,
            request.titles,
        )
        for start in range(0, len(text), 48):
            yield text[start : start + 48]


def _similar(a: str, b: str) -> bool:
    ta, tb = set(tokenize(a)), set(tokenize(b))
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) > 0.8


def _is_registry_boilerplate(sentence: str) -> bool:
    lowered = sentence.lower()
    return lowered.startswith(("this is the registry record", "clinicaltrials.gov study", "nice technology appraisal ta")) and "recommend" not in lowered


ACRONYM = re.compile(r"\(([A-Za-z][A-Za-z0-9 \-]{2,24})\)\s*$")


def _names_trial(query: str, title: str) -> bool:
    """True when the question names the trial acronym given in parentheses in a source title."""
    match = ACRONYM.search(title)
    if not match:
        return False
    acronym = match.group(1).lower()
    return acronym in query.lower() or acronym.replace("-", " ") in query.lower()
