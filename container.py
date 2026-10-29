"""Service container: builds every long lived component once, from settings."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from carina.audit import AuditLog
from carina.cache import AnswerCache, build_cache
from carina.config import Settings, get_settings
from carina.generation.extractive import ExtractiveGenerator
from carina.generation.pipeline import RAGPipeline
from carina.llm.anthropic_provider import AnthropicProvider
from carina.llm.base import LLMProvider
from carina.llm.ollama_provider import OllamaProvider
from carina.llm.openai_provider import OpenAIProvider
from carina.llm.router import ProviderRouter
from carina.retrieval.embedder import Embedder, build_embedder
from carina.retrieval.hybrid import HybridRetriever
from carina.retrieval.index import KnowledgeIndex
from carina.retrieval.reranker import build_reranker
from carina.retrieval.vector_store import QdrantVectorStore

log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    index: KnowledgeIndex
    embedder: Embedder
    retriever: HybridRetriever
    router: ProviderRouter
    audit: AuditLog
    cache: AnswerCache
    pipeline: RAGPipeline
    index_origin: str


def load_index(settings: Settings, embedder: Embedder) -> tuple[KnowledgeIndex, str]:
    vectors = None
    if settings.vector_backend == "qdrant":
        vectors = QdrantVectorStore(settings.qdrant_url, settings.qdrant_collection, embedder.dim)
    if KnowledgeIndex.exists(settings.index_dir):
        return KnowledgeIndex.load(settings.index_dir, vectors), "persisted"
    # No built index yet: index the verified seed snapshot in memory so the service still answers.
    from ingestion.pipeline import build_index  # local import keeps the API importable without ingestion extras

    log.warning("no persisted index; building from the seed snapshot in memory")
    index = build_index(settings, include_seed=True, include_raw=False)
    return index, "seed"


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()
    embedder = build_embedder(settings.embedding_backend, settings.embedding_model, settings.embedding_dim)
    index, origin = load_index(settings, embedder)
    reranker = build_reranker(settings.reranker_backend, settings.reranker_model, index.bm25.idf)
    retriever = HybridRetriever(index, embedder, reranker, settings)
    providers: dict[str, LLMProvider] = {
        "anthropic": AnthropicProvider(settings.anthropic_model, settings.llm_timeout_s),
        "openai": OpenAIProvider(settings.openai_model, settings.llm_timeout_s),
        "ollama": OllamaProvider(settings.ollama_model, settings.ollama_url, settings.llm_timeout_s * 2),
        "extractive": ExtractiveGenerator(index.bm25.idf),
    }
    router = ProviderRouter(
        providers,
        [settings.llm_provider, *settings.llm_fallbacks],
        settings.circuit_failure_threshold,
        settings.circuit_reset_s,
    )
    audit = AuditLog(settings.audit_path, settings.feedback_path, settings.audit_salt)
    cache = build_cache(settings.cache_backend, settings.redis_url, settings.cache_ttl_s)
    pipeline = RAGPipeline(settings, retriever, router, audit, cache)
    return Container(settings, index, embedder, retriever, router, audit, cache, pipeline, origin)


@lru_cache(maxsize=1)
def get_container() -> Container:
    return build_container()
