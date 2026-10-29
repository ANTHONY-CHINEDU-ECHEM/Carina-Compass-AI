"""Okapi BM25 over clinical tokens, with on disk persistence.

Implemented directly (rather than through a library) so that tokenisation,
document length normalisation and persistence stay under our control and the
index can be rebuilt in batches as the corpus streams from disk.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from carina.retrieval.tokenizer import tokenize


class BM25Index:
    def __init__(self, k1: float = 1.4, b: float = 0.72) -> None:
        self.k1 = k1
        self.b = b
        self.doc_ids: list[str] = []
        self.doc_len: list[int] = []
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.doc_freq: dict[str, int] = {}
        self._avgdl = 0.0

    def __len__(self) -> int:
        return len(self.doc_ids)

    def add(self, items: Iterable[tuple[str, str]]) -> None:
        for chunk_id, text in items:
            tokens = tokenize(text)
            idx = len(self.doc_ids)
            self.doc_ids.append(chunk_id)
            self.doc_len.append(len(tokens))
            for term, freq in Counter(tokens).items():
                self.postings[term].append((idx, freq))
        self._finalise()

    def _finalise(self) -> None:
        self.doc_freq = {term: len(post) for term, post in self.postings.items()}
        self._avgdl = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0

    def idf(self, term: str) -> float:
        n = len(self.doc_ids)
        df = self.doc_freq.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 40) -> list[tuple[str, float]]:
        if not self.doc_ids:
            return []
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokenize(query)):
            postings = self.postings.get(term)
            if not postings:
                continue
            idf = self.idf(term)
            for idx, freq in postings:
                norm = self.k1 * (1 - self.b + self.b * self.doc_len[idx] / (self._avgdl or 1))
                scores[idx] += idf * freq * (self.k1 + 1) / (freq + norm)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return [(self.doc_ids[idx], score) for idx, score in ranked]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "k1": self.k1,
            "b": self.b,
            "doc_ids": self.doc_ids,
            "doc_len": self.doc_len,
            "postings": self.postings,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> BM25Index:
        payload = json.loads(path.read_text(encoding="utf-8"))
        index = cls(payload["k1"], payload["b"])
        index.doc_ids = payload["doc_ids"]
        index.doc_len = payload["doc_len"]
        index.postings = defaultdict(list, {k: [tuple(p) for p in v] for k, v in payload["postings"].items()})
        index._finalise()
        return index
