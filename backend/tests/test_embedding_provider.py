"""Unit tests for EmbeddingProvider service (P0-01)."""

import pytest
from backend.app.services.embedding_provider import (
    DeterministicEmbeddingProvider,
    GeminiEmbeddingProvider,
    get_embedding_provider,
)


def test_deterministic_embedding_provider():
    provider = DeterministicEmbeddingProvider(dimension=768)
    v1 = provider.embed_text("test query")
    v2 = provider.embed_text("test query")
    v3 = provider.embed_text("different query")

    assert len(v1) == 768
    assert v1 == v2
    assert v1 != v3


@pytest.mark.asyncio
async def test_gemini_embedding_provider_fallback_without_key():
    provider = GeminiEmbeddingProvider(api_key=None)
    vec = await provider.embed_text_async("sample text")
    assert len(vec) == 768


def test_get_embedding_provider_factory():
    provider = get_embedding_provider()
    vec = provider.embed_text("sample")
    assert len(vec) == 768
