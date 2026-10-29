"""Claim level faithfulness: does each cited sentence say what its sources say?

A citation can be valid while the sentence embellishes the passage it cites.
Each factual sentence is compared with the union of its cited passages using
a weighted token support score in which drugs, biomarkers, numbers and rare
words count more than common words. The share of supported sentences is
reported as claim support and gates the "grounded" label.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from carina.generation.citations import CITATION, is_factual, split_answer_sentences
from carina.retrieval.reranker import DECISIVE
from carina.retrieval.tokenizer import tokenize

SUPPORT_THRESHOLD = 0.6


@dataclass
class ClaimCheck:
    sentence: str
    cited: list[int]
    support: float
    supported: bool


@dataclass
class FaithfulnessReport:
    claims: list[ClaimCheck] = field(default_factory=list)

    @property
    def claim_support(self) -> float:
        if not self.claims:
            return 0.0
        return sum(1 for c in self.claims if c.supported) / len(self.claims)

    def unsupported(self) -> list[str]:
        return [c.sentence for c in self.claims if not c.supported]

    def as_dict(self) -> dict[str, object]:
        return {
            "claim_support": round(self.claim_support, 3),
            "claims": len(self.claims),
            "unsupported_claims": self.unsupported()[:5],
        }


def assess(answer: str, sources: dict[int, str], idf: Callable[[str], float] | None = None) -> FaithfulnessReport:
    idf = idf or (lambda _t: 1.0)
    report = FaithfulnessReport()
    for sentence in split_answer_sentences(answer):
        if not is_factual(sentence):
            continue
        ids = [int(i) for i in CITATION.findall(sentence)]
        if not ids:
            report.claims.append(ClaimCheck(sentence, [], 0.0, False))
            continue
        claim = re.sub(CITATION, "", sentence)
        claim_terms = set(tokenize(claim))
        if not claim_terms:
            continue
        evidence_terms = set(tokenize(" ".join(sources.get(i, "") for i in ids)))
        weights = {t: max(0.3, idf(t)) * (2.5 if DECISIVE.match(t) else 1.0) for t in claim_terms}
        total = sum(weights.values())
        supported = sum(w for t, w in weights.items() if t in evidence_terms)
        score = supported / total if total else 0.0
        decisive_missing = [t for t in claim_terms if DECISIVE.match(t) and t not in evidence_terms]
        ok = score >= SUPPORT_THRESHOLD and not decisive_missing
        report.claims.append(ClaimCheck(sentence, ids, round(score, 3), ok))
    return report
