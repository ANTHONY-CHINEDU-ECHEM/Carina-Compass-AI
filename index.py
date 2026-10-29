"""The knowledge index: chunks, BM25, vectors and the build manifest.

The index is built by the ingestion pipeline and loaded by the API. In memory
mode everything is persisted under data/index; in production the vectors live
in Qdrant and only the chunk store, BM25 postings and manifest are on disk.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from carina.domain import Chunk, Document, SourceType
from carina.retrieval.bm25 import BM25Index
from carina.retrieval.embedder import Embedder
from carina.retrieval.vector_store import MemoryVectorStore, VectorStore

log = logging.getLogger(__name__)


@dataclass
class KnowledgeIndex:
    chunks: dict[str, Chunk] = field(default_factory=dict)
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    bm25: BM25Index = field(default_factory=BM25Index)
    vectors: VectorStore = field(default_factory=MemoryVectorStore)
    manifest: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.chunks)

    def add(self, documents: Iterable[Document], chunks: Iterable[Chunk], embedder: Embedder, batch_size: int = 256) -> None:
        for doc in documents:
            self.documents[doc.doc_id] = _doc_summary(doc)
        batch: list[Chunk] = []
        for chunk in chunks:
            batch.append(chunk)
            if len(batch) >= batch_size:
                self._add_batch(batch, embedder)
                batch = []
        if batch:
            self._add_batch(batch, embedder)

    def _add_batch(self, batch: list[Chunk], embedder: Embedder) -> None:
        for chunk in batch:
            self.chunks[chunk.chunk_id] = chunk
        self.bm25.add((c.chunk_id, _index_text(c)) for c in batch)
        vectors = embedder.embed([_index_text(c) for c in batch])
        payloads = [
            {
                "doc_id": c.doc_id,
                "source": c.source.value,
                "jurisdiction": c.jurisdiction.value,
                "evidence_grade": int(c.evidence_grade),
                "year": c.year,
                "biomarkers": c.metadata.get("biomarkers", []),
            }
            for c in batch
        ]
        self.vectors.upsert([c.chunk_id for c in batch], vectors, payloads)

    def trials(self) -> Iterator[dict[str, Any]]:
        for doc in self.documents.values():
            if doc["source"] == SourceType.CLINICAL_TRIAL.value:
                yield doc["metadata"] | {"title": doc["title"], "nct_id": doc["identifiers"].get("nct")}

    def build_manifest(self, embedder_name: str, sources: dict[str, Any] | None = None) -> dict[str, Any]:
        by_source: dict[str, int] = {}
        by_grade: dict[str, int] = {}
        licences: dict[str, int] = {}
        for doc in self.documents.values():
            by_source[doc["source"]] = by_source.get(doc["source"], 0) + 1
            by_grade[str(doc["evidence_grade"])] = by_grade.get(str(doc["evidence_grade"]), 0) + 1
            licences[doc["licence_key"]] = licences.get(doc["licence_key"], 0) + 1
        self.manifest = {
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "documents": len(self.documents),
            "chunks": len(self.chunks),
            "documents_by_source": dict(sorted(by_source.items())),
            "documents_by_evidence_grade": dict(sorted(by_grade.items())),
            "licences": licences,
            "embedder": embedder_name,
            "sources": sources or {},
        }
        return self.manifest

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "chunks.jsonl").open("w", encoding="utf-8") as handle:
            for chunk in self.chunks.values():
                handle.write(chunk.model_dump_json() + "\n")
        (directory / "documents.json").write_text(json.dumps(self.documents), encoding="utf-8")
        self.bm25.save(directory / "bm25.json")
        if isinstance(self.vectors, MemoryVectorStore):
            self.vectors.save(directory)
        (directory / "manifest.json").write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")
        log.info("index saved", extra={"chunks": len(self.chunks), "directory": str(directory)})

    @classmethod
    def load(cls, directory: Path, vectors: VectorStore | None = None) -> KnowledgeIndex:
        index = cls()
        with (directory / "chunks.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                chunk = Chunk.model_validate_json(line)
                index.chunks[chunk.chunk_id] = chunk
        index.documents = json.loads((directory / "documents.json").read_text(encoding="utf-8"))
        index.bm25 = BM25Index.load(directory / "bm25.json")
        index.vectors = vectors or MemoryVectorStore.load(directory)
        manifest = directory / "manifest.json"
        index.manifest = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        return index

    @staticmethod
    def exists(directory: Path) -> bool:
        return (directory / "chunks.jsonl").exists() and (directory / "bm25.json").exists()


def _index_text(chunk: Chunk) -> str:
    """Title and section are indexed with the passage so short chunks keep their context."""
    header = chunk.title if not chunk.section else f"{chunk.title}. {chunk.section}"
    return f"{header}. {chunk.text}"


def _doc_summary(doc: Document) -> dict[str, Any]:
    return {
        "doc_id": doc.doc_id,
        "source": doc.source.value,
        "title": doc.title,
        "url": doc.url,
        "year": doc.year,
        "jurisdiction": doc.jurisdiction.value,
        "evidence_grade": int(doc.evidence_grade),
        "licence_key": doc.licence_key,
        "identifiers": doc.identifiers,
        "metadata": doc.metadata,
        "superseded_by": doc.superseded_by,
    }
