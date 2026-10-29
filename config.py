"""Typed settings read from the environment with the CC_ prefix."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

CsvList = Annotated[list[str], NoDecode]

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # Data locations
    data_dir: Path = REPO_ROOT / "data"
    seed_dir: Path = REPO_ROOT / "ingestion" / "data" / "seed"
    knowledge_dir: Path = PACKAGE_ROOT / "knowledge"
    index_dir: Path = REPO_ROOT / "data" / "index"
    audit_path: Path = REPO_ROOT / "data" / "audit" / "audit.jsonl"
    feedback_path: Path = REPO_ROOT / "data" / "audit" / "feedback.jsonl"

    # Language models
    llm_provider: Literal["anthropic", "openai", "ollama", "extractive"] = "anthropic"
    llm_fallbacks: CsvList = Field(default_factory=lambda: ["openai", "extractive"])
    anthropic_model: str = "claude-sonnet-5-5"
    openai_model: str = "gpt-4.1"
    ollama_model: str = "llama3.1:8b"
    ollama_url: str = "http://localhost:11434"
    llm_max_tokens: int = 1400
    llm_temperature: float = 0.1
    llm_timeout_s: float = 60.0
    circuit_failure_threshold: int = 3
    circuit_reset_s: float = 60.0

    # Retrieval
    embedding_backend: Literal["hashing", "sentence_transformers"] = "hashing"
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dim: int = 768
    reranker_backend: Literal["lexical", "cross_encoder"] = "lexical"
    reranker_model: str = "BAAI/bge-reranker-base"
    vector_backend: Literal["memory", "qdrant"] = "memory"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "carina_compass"
    top_k_dense: int = 40
    top_k_sparse: int = 40
    top_k_rerank: int = 24
    top_k_final: int = 8
    max_chunks_per_doc: int = 2
    rrf_k: int = 60
    evidence_weight: float = 0.30
    recency_weight: float = 0.10
    recency_half_life_years: float = 6.0
    uk_bonus: float = 0.10
    biomarker_bonus: float = 0.20
    setting_bonus: float = 0.40
    histology_bonus: float = 0.12
    superseded_penalty: float = 0.5

    # Answer gates
    min_evidence_score: float = 0.30
    min_query_coverage: float = 0.4
    min_citation_coverage: float = 0.9
    min_faithfulness: float = 0.5

    # Behaviour
    tool_routing: bool = True
    stream_chunk_chars: int = 48

    # Security and operations
    api_keys: CsvList = Field(default_factory=list)
    admin_api_keys: CsvList = Field(default_factory=list)
    rate_limit_per_minute: int = 60
    audit_salt: str = "local-development-salt-change-me"
    cache_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_s: int = 3600
    cors_origins: CsvList = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"])

    @field_validator("llm_fallbacks", "api_keys", "admin_api_keys", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
