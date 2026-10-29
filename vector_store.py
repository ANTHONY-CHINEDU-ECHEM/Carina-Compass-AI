"""Vector stores: in memory (NumPy) for development and CI, Qdrant for production.

Both expose the same small interface so the hybrid retriever does not care
which one is configured. Qdrant payload indexes on source, jurisdiction and
evidence grade support filtered search from the /v1/search endpoint.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Protocol

import numpy as np


class VectorStore(Protocol):
    def upsert(self, ids: list[str], vectors: np.ndarray, payloads: list[dict[str, Any]]) -> None: ...

    def search(self, vector: np.ndarray, top_k: int, filters: dict[str, Any] | None = None) -> list[tuple[str, float]]: ...

    def count(self) -> int: ...


class MemoryVectorStore:
    def __init__(self) -> None:
        self.ids: list[str] = []
        self.matrix = np.zeros((0, 0), dtype=np.float32)
        self.payloads: list[dict[str, Any]] = []

    def upsert(self, ids: list[str], vectors: np.ndarray, payloads: list[dict[str, Any]]) -> None:
        if self.matrix.size == 0:
            self.matrix = vectors.astype(np.float32)
        else:
            self.matrix = np.vstack([self.matrix, vectors.astype(np.float32)])
        self.ids.extend(ids)
        self.payloads.extend(payloads)

    def search(self, vector: np.ndarray, top_k: int, filters: dict[str, Any] | None = None) -> list[tuple[str, float]]:
        if not self.ids:
            return []
        scores = self.matrix @ vector.astype(np.float32)
        if filters:
            mask = np.array([_passes(p, filters) for p in self.payloads])
            scores = np.where(mask, scores, -np.inf)
        k = min(top_k, len(self.ids))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(self.ids[i], float(scores[i])) for i in top if np.isfinite(scores[i])]

    def count(self) -> int:
        return len(self.ids)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / "vectors.npy", self.matrix)
        (directory / "vector_ids.json").write_text(json.dumps({"ids": self.ids, "payloads": self.payloads}), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> MemoryVectorStore:
        store = cls()
        store.matrix = np.load(directory / "vectors.npy")
        meta = json.loads((directory / "vector_ids.json").read_text(encoding="utf-8"))
        store.ids = meta["ids"]
        store.payloads = meta["payloads"]
        return store


def _passes(payload: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, wanted in filters.items():
        value = payload.get(key)
        if key == "min_evidence_grade":
            if (payload.get("evidence_grade") or 0) < wanted:
                return False
        elif isinstance(wanted, list):
            if value not in wanted:
                return False
        elif value != wanted:
            return False
    return True


class QdrantVectorStore:
    """Qdrant backed store. Point ids are UUIDv5 of the chunk id for idempotent upserts."""

    def __init__(self, url: str, collection: str, dim: int) -> None:
        from qdrant_client import QdrantClient  # optional dependency
        from qdrant_client.http import models

        self._models = models
        self.client = QdrantClient(url=url, timeout=30)
        self.collection = collection
        existing = {c.name for c in self.client.get_collections().collections}
        if collection not in existing:
            self.client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
                hnsw_config=models.HnswConfigDiff(m=32, ef_construct=256),
            )
            for field_name, schema in (
                ("source", models.PayloadSchemaType.KEYWORD),
                ("jurisdiction", models.PayloadSchemaType.KEYWORD),
                ("evidence_grade", models.PayloadSchemaType.INTEGER),
                ("year", models.PayloadSchemaType.INTEGER),
                ("biomarkers", models.PayloadSchemaType.KEYWORD),
            ):
                self.client.create_payload_index(collection, field_name=field_name, field_schema=schema)

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))

    def upsert(self, ids: list[str], vectors: np.ndarray, payloads: list[dict[str, Any]]) -> None:
        models = self._models
        points = [
            models.PointStruct(id=self._point_id(cid), vector=vec.tolist(), payload={**payload, "chunk_id": cid})
            for cid, vec, payload in zip(ids, vectors, payloads, strict=True)
        ]
        for start in range(0, len(points), 256):
            self.client.upsert(self.collection, points=points[start : start + 256], wait=True)

    def search(self, vector: np.ndarray, top_k: int, filters: dict[str, Any] | None = None) -> list[tuple[str, float]]:
        models = self._models
        conditions = []
        for key, wanted in (filters or {}).items():
            if key == "min_evidence_grade":
                conditions.append(models.FieldCondition(key="evidence_grade", range=models.Range(gte=wanted)))
            elif isinstance(wanted, list):
                conditions.append(models.FieldCondition(key=key, match=models.MatchAny(any=wanted)))
            else:
                conditions.append(models.FieldCondition(key=key, match=models.MatchValue(value=wanted)))
        hits = self.client.search(
            collection_name=self.collection,
            query_vector=vector.tolist(),
            limit=top_k,
            query_filter=models.Filter(must=conditions) if conditions else None,
            with_payload=["chunk_id"],
        )
        return [(hit.payload["chunk_id"], float(hit.score)) for hit in hits if hit.payload]

    def count(self) -> int:
        return int(self.client.count(self.collection, exact=True).count)
