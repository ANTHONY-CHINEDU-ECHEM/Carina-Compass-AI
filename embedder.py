"""Dense embedders.

The production embedder is BGE base (sentence transformers). The hashing
embedder is a deterministic, dependency free fallback used in CI and offline
development: signed feature hashing of clinical unigrams and bigrams, L2
normalised. It is weaker than a neural model but it keeps every test and the
evaluation gate reproducible without downloading weights.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np

from carina.retrieval.tokenizer import tokenize


class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, texts: list[str], *, is_query: bool = False) -> np.ndarray: ...


class HashingEmbedder:
    name = "hashing"

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        return value % self.dim, 1.0 if (value >> 63) & 1 else -1.0

    def embed(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = tokenize(text)
            features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
            for feature in features:
                col, sign = self._bucket(feature)
                matrix[row, col] += sign * (1.5 if "_" not in feature else 1.0)
            norm = np.linalg.norm(matrix[row])
            if norm > 0:
                matrix[row] /= norm
        return matrix


class SentenceTransformerEmbedder:
    """BGE style embedder. Queries get the retrieval instruction prefix."""

    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # imported lazily: heavy optional dependency

        self.model = SentenceTransformer(model_name)
        self.dim = int(self.model.get_sentence_embedding_dimension())
        self.name = model_name

    def embed(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        if is_query:
            texts = [self.QUERY_PREFIX + t for t in texts]
        vectors = self.model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype=np.float32)


def build_embedder(backend: str, model_name: str, dim: int) -> Embedder:
    if backend == "sentence_transformers":
        return SentenceTransformerEmbedder(model_name)
    return HashingEmbedder(dim)
