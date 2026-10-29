"""Answerability gate: abstain rather than guess.

Two checks run on the retrieved evidence before any model is called:
  1. Evidence strength: the best final score must reach min_evidence_score.
  2. Query coverage: the question's most specific terms (weighted by inverse
     document frequency) must appear in the top passages. A question about a
     drug or biomarker the corpus never mentions is not answerable, however
     well the generic words match.
Emergencies are never held back by this gate.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from carina.domain import ScoredChunk
from carina.retrieval.index import _index_text
from carina.retrieval.reranker import DECISIVE
from carina.retrieval.tokenizer import tokenize


@dataclass
class Answerability:
    answerable: bool
    best_score: float
    query_coverage: float
    missing_terms: list[str]
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "answerable": self.answerable,
            "best_score": round(self.best_score, 4),
            "query_coverage": round(self.query_coverage, 3),
            "missing_terms": self.missing_terms,
            "reason": self.reason,
        }


DRUG_SUFFIX = re.compile(r"[a-z]{3,}(mab|nib|rasib|tinib|sertib|lisib|ectedin|tecan|platin|taxel|rubicin|parib|ciclib|tamab|limab|zumab|ximab)$")


def assess(
    question: str,
    results: list[ScoredChunk],
    idf: Callable[[str], float],
    *,
    min_score: float,
    min_coverage: float,
    top_n: int = 5,
    required_entities: list[str] | None = None,
    expansions: list[str] | None = None,
) -> Answerability:
    if not results:
        return Answerability(False, 0.0, 0.0, [], "no evidence retrieved")
    best = max(r.final_score for r in results)
    terms = list(dict.fromkeys(tokenize(question)))
    if not terms:
        return Answerability(best >= min_score, best, 0.0, [], "no searchable terms")
    # Patient numbers (age, weight, percentages) describe the case, not the evidence, so they carry little weight.
    weights = {t: (0.2 if _numeric(t) else idf(t) * (2.0 if DECISIVE.match(t) else 1.0)) for t in terms}
    evidence_terms: set[str] = set()
    for item in results[:top_n]:
        evidence_terms.update(tokenize(_index_text(item.chunk)))
    # A question term counts as covered when an expansion of the question is present,
    # so "first line" is answered by guidance that says "untreated".
    expansion_hits = {t for phrase in (expansions or []) for t in tokenize(phrase) if t in evidence_terms}
    if expansion_hits:
        evidence_terms = evidence_terms | _expanded_terms(question, expansion_hits)
    total = sum(weights.values()) or 1.0
    covered = sum(w for t, w in weights.items() if t in evidence_terms)
    coverage = covered / total
    # The single most specific term (highest weight) must be present.
    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    missing = [t for t, _ in ranked if t not in evidence_terms]
    decisive_missing = [t for t in missing if (DECISIVE.match(t) or DRUG_SUFFIX.match(t)) and not _numeric(t)]
    for entity in required_entities or []:
        parts = tokenize(entity)
        if parts and not all(p in evidence_terms for p in parts) and entity not in decisive_missing:
            decisive_missing.append(entity)
    if best < min_score:
        return Answerability(False, best, coverage, missing[:5], "evidence too weak")
    if coverage < min_coverage:
        return Answerability(False, best, coverage, missing[:5], "question terms not covered by evidence")
    if decisive_missing:
        return Answerability(False, best, coverage, decisive_missing[:5], "a named medicine or biomarker is absent from the evidence")
    return Answerability(True, best, coverage, missing[:5], "answerable")


def _numeric(token: str) -> bool:
    return token[:1].isdigit()


def _expanded_terms(question: str, hits: set[str]) -> set[str]:
    """Question terms whose synonym expansion was found in the evidence."""
    from carina.clinical.understanding import normalise_text

    lowered, _ = normalise_text(question)
    from carina.knowledge import load

    credited: set[str] = set()
    for phrase, alternatives in load("lexicon.yaml").get("synonyms", {}).items():
        if phrase in lowered and any(t in hits for alt in alternatives for t in tokenize(alt)):
            credited.update(tokenize(phrase))
    for abbreviation, expansion in load("lexicon.yaml").get("abbreviations", {}).items():
        if any(t in hits for t in tokenize(expansion)):
            credited.update(tokenize(abbreviation))
    return credited
