"""Ingestion pipeline: harvest, checkpoint, deduplicate, apply currency, chunk, embed, index.

Raw documents are streamed to data/raw/<source>.jsonl as they are harvested,
so an interrupted run resumes without repeating requests. Processing reads
the checkpoints back, which keeps memory flat even for several hundred
thousand PubMed records.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from carina.config import Settings
from carina.domain import Document
from carina.retrieval.embedder import build_embedder
from carina.retrieval.index import KnowledgeIndex
from carina.retrieval.supersession import replaced_by
from carina.retrieval.vector_store import MemoryVectorStore, QdrantVectorStore
from ingestion.processing.chunker import chunk_document
from ingestion.processing.dedup import deduplicate
from ingestion.seed import load_seed_documents
from ingestion.sources.base import Source
from ingestion.sources.civic import CivicSource
from ingestion.sources.clinicaltrials import ClinicalTrialsSource
from ingestion.sources.europepmc import EuropePMCSource
from ingestion.sources.medlineplus import MedlinePlusSource
from ingestion.sources.nice import NiceSource
from ingestion.sources.openfda import OpenFDASource
from ingestion.sources.pdq import PDQSource
from ingestion.sources.pubmed import PubMedSource

log = logging.getLogger(__name__)

CONNECTORS: dict[str, type[Source]] = {
    "nice": NiceSource,
    "nci_pdq": PDQSource,
    "pubmed": PubMedSource,
    "europe_pmc": EuropePMCSource,
    "clinical_trials": ClinicalTrialsSource,
    "civic": CivicSource,
    "openfda": OpenFDASource,
    "medlineplus": MedlinePlusSource,
}

CORPUS_CONFIG = Path(__file__).resolve().parent / "config" / "corpus.yaml"


def load_corpus_config(path: Path = CORPUS_CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _checkpoint_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as handle:
        return {json.loads(line)["doc_id"] for line in handle if line.strip()}


def harvest(settings: Settings, only: list[str] | None = None, limit: int | None = None) -> dict[str, dict[str, Any]]:
    config = load_corpus_config()["sources"]
    raw_dir = settings.data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict[str, Any]] = {}
    for name, cls in CONNECTORS.items():
        if only and name not in only:
            continue
        source = cls(config.get(name, {}))
        if not source.enabled():
            report[name] = {"status": "disabled"}
            continue
        path = raw_dir / f"{name}.jsonl"
        seen = _checkpoint_ids(path)
        started = time.perf_counter()
        added = 0
        try:
            with path.open("a", encoding="utf-8") as handle:
                for doc in source.harvest(limit=limit):
                    if doc.doc_id in seen:
                        continue
                    handle.write(doc.model_dump_json() + "\n")
                    seen.add(doc.doc_id)
                    added += 1
            status = "ok"
        except Exception as exc:
            log.exception("source failed", extra={"source": name})
            status = f"failed: {exc}"[:200]
        report[name] = {"status": status, "added": added, "total": len(seen), "seconds": round(time.perf_counter() - started, 1)}
        log.info("harvested", extra={"source": name, **report[name]})
    return report


def read_raw(settings: Settings) -> Iterator[Document]:
    raw_dir = settings.data_dir / "raw"
    for path in sorted(raw_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield Document.model_validate_json(line)


def apply_currency(documents: list[Document]) -> int:
    """Mark documents whose guidance reference has been replaced."""
    graph = replaced_by()
    marked = 0
    for doc in documents:
        ref = (doc.identifiers.get("nice") or doc.identifiers.get("edition") or "").upper()
        if ref in graph and not doc.superseded_by:
            doc.superseded_by = graph[ref]
            marked += 1
    return marked


def build_index(settings: Settings, include_seed: bool = True, include_raw: bool = True) -> KnowledgeIndex:
    started = time.perf_counter()
    documents: list[Document] = []
    if include_seed:
        documents.extend(load_seed_documents(settings.seed_dir))
    if include_raw:
        documents.extend(read_raw(settings))
    unique, collapsed = deduplicate(documents)
    superseded = apply_currency(unique)
    embedder = build_embedder(settings.embedding_backend, settings.embedding_model, settings.embedding_dim)
    vectors = QdrantVectorStore(settings.qdrant_url, settings.qdrant_collection, embedder.dim) if settings.vector_backend == "qdrant" else MemoryVectorStore()
    index = KnowledgeIndex(vectors=vectors)
    chunks = (chunk for doc in unique for chunk in chunk_document(doc))
    index.add(unique, chunks, embedder)
    index.build_manifest(
        embedder.name,
        sources={
            "input_documents": len(documents),
            "duplicates_collapsed": collapsed,
            "superseded_marked": superseded,
            "build_seconds": round(time.perf_counter() - started, 1),
        },
    )
    return index


def run(settings: Settings, only: list[str] | None = None, limit: int | None = None, skip_harvest: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {}
    if not skip_harvest:
        report["harvest"] = harvest(settings, only, limit)
    index = build_index(settings)
    index.save(settings.index_dir)
    report["manifest"] = index.manifest
    return report
