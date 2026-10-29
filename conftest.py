"""Shared fixtures. Every test runs offline against the verified seed snapshot."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="carina-tests-"))
os.environ.update(
    {
        "CC_ENVIRONMENT": "test",
        "CC_LLM_PROVIDER": "extractive",
        "CC_LLM_FALLBACKS": "extractive",
        "CC_EMBEDDING_BACKEND": "hashing",
        "CC_RERANKER_BACKEND": "lexical",
        "CC_VECTOR_BACKEND": "memory",
        "CC_CACHE_BACKEND": "memory",
        "CC_INDEX_DIR": str(_TMP / "index-absent"),
        "CC_AUDIT_PATH": str(_TMP / "audit.jsonl"),
        "CC_FEEDBACK_PATH": str(_TMP / "feedback.jsonl"),
        "CC_RATE_LIMIT_PER_MINUTE": "1000",
    }
)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)


@pytest.fixture(scope="session")
def settings():
    from carina.config import get_settings

    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def container(settings):
    from carina.container import get_container

    get_container.cache_clear()
    return get_container()


@pytest.fixture(scope="session")
def client(container):
    from fastapi.testclient import TestClient

    from carina.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def audit_path(settings) -> Path:
    return settings.audit_path
