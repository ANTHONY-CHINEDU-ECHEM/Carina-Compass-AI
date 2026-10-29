"""Rerankers.

The cross encoder (BGE reranker base) reads query and passage together and is
used in production. The lexical reranker is the deterministic fallback: an IDF
weighted coverage of query terms with extra weight for clinically decisive
tokens (biomarkers, drugs, numbers), plus a proximity bonus.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Protocol

from carina.retrieval.tokenizer import tokenize

DECISIVE = re.compile(r"^(?:bm_[a-z0-9_]+|[a-z]\d{2,4}[a-z]|exon\d+|pdl1|egfr|alk|ros1|kras|braf|met|ret|ntrk\d?|her2|ta\d+|ng\d+|nct\d+|\d+(?:\.\d+)?%?)$")


class Reranker(Protocol):
    def score(self, query: str, passages: list[str], expansions: str = "") -> list[float]: ...


class LexicalReranker:
    def __init__(self, idf: Callable[[str], float] | None = None) -> None:
        self.idf = idf or (lambda _term: 1.0)

    def score(self, query: str, passages: list[str], expansions: str = "") -> list[float]:
        """Score passages by weighted coverage of the question.

        Expansion terms (synonyms such as "untreated" for "first line") earn
        most of the credit, capped at 40% of the question weight, so a passage written
        in guideline language is not penalised for not echoing the question.
        """
        q_terms = list(dict.fromkeys(tokenize(query)))
        if not q_terms:
            return [0.0] * len(passages)
        weights = {t: _term_weight(t, self.idf) for t in q_terms}
        expansion_weights = {t: 0.8 * self.idf(t) for t in dict.fromkeys(tokenize(expansions)) if t not in weights}
        total = sum(weights.values()) or 1.0
        scores = []
        for passage in passages:
            p_tokens = tokenize(passage)
            p_set = set(p_tokens)
            core = sum(w for t, w in weights.items() if t in p_set)
            bonus = min(0.4 * total, sum(w for t, w in expansion_weights.items() if t in p_set))
            coverage = min(1.0, (core + bonus) / total)
            positions = [i for i, t in enumerate(p_tokens) if t in weights]
            proximity = 0.0
            if len(positions) > 1:
                span = positions[-1] - positions[0] + 1
                proximity = min(1.0, len(set(p_tokens[i] for i in positions)) / span * 3)
            scores.append(0.85 * coverage + 0.15 * proximity)
        return scores


class CrossEncoderReranker:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder  # optional dependency

        self.model = CrossEncoder(model_name, max_length=512)

    def score(self, query: str, passages: list[str], expansions: str = "") -> list[float]:
        if not passages:
            return []
        logits = self.model.predict([(query, p) for p in passages], batch_size=16, show_progress_bar=False)
        return [1 / (1 + math.exp(-float(x))) for x in logits]


def build_reranker(backend: str, model_name: str, idf: Callable[[str], float] | None = None) -> Reranker:
    if backend == "cross_encoder":
        return CrossEncoderReranker(model_name)
    return LexicalReranker(idf)


def _term_weight(term: str, idf: Callable[[str], float]) -> float:
    """Clinical concepts and biomarkers count double; bare patient numbers (age, PD L1 value) count little."""
    if term[:1].isdigit():
        return 0.3
    return idf(term) * (2.0 if DECISIVE.match(term) else 1.0)
