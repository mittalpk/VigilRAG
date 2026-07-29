"""
Unit & Integration Tests for US-033 Retrieval Reranking (Cross-Encoder Step).
"""

from unittest.mock import MagicMock, patch
import pytest

from backend.app.schemas import EvidenceItem
from backend.app.services.cross_encoder_reranker import (
    CrossEncoderReranker,
    init_cross_encoder_model,
)
from backend.app.services.hybrid_retrieval_engine import HybridRetrievalEngine
from backend.app.models import AsyncSessionLocal, Chunk, init_db


@pytest.fixture
def candidate_evidence():
    return [
        EvidenceItem(
            chunk_id="chk-001",
            content="General overview of company employee benefits and holiday policies.",
            source_url="https://example.com/1",
            relevance_score=0.85,
            source_id="src-001",
        ),
        EvidenceItem(
            chunk_id="chk-002",
            content="Detailed step-by-step instructions for resetting production database admin passwords.",
            source_url="https://example.com/2",
            relevance_score=0.80,
            source_id="src-002",
        ),
        EvidenceItem(
            chunk_id="chk-003",
            content="Summary of quarterly financial earnings and revenue projections.",
            source_url="https://example.com/3",
            relevance_score=0.75,
            source_id="src-003",
        ),
    ]


def test_cross_encoder_reranking_order_and_score(candidate_evidence):
    reranker = CrossEncoderReranker()
    query = "How to reset production database admin password?"

    # Execute reranking
    reranked = reranker.rerank(query, candidate_evidence)

    assert len(reranked) == 3
    # Check that rerank_score is populated for all items
    for item in reranked:
        assert item.rerank_score is not None
        assert isinstance(item.rerank_score, float)

    # Verify that the database password chunk is reordered to rank #1
    assert reranked[0].chunk_id == "chk-002"


def test_reranker_fallback_on_exception(candidate_evidence):
    reranker = CrossEncoderReranker()
    query = "Reset database password"

    with patch("backend.app.services.cross_encoder_reranker.get_cross_encoder_model", side_effect=Exception("Model crash")):
        reranked = reranker.rerank(query, candidate_evidence)
        assert len(reranked) == 3
        # Should retain candidate list without raising
        for item in reranked:
            assert item.rerank_score is not None


@pytest.mark.asyncio
async def test_hybrid_retrieval_with_reranking_integration():
    await init_db()

    async with AsyncSessionLocal() as session:
        # Insert test chunk
        chk = Chunk(
            id="chk-rerank-test-01",
            source_id="src-test",
            document_id="doc-test",
            content="How to setup distributed OpenTelemetry tracing and Jaeger exporter.",
            permissions_ref="public",
            checksum="chksum123",
            embedding_vector_str="[0.1, 0.2, 0.3]",
        )
        session.add(chk)
        await session.commit()

        engine = HybridRetrievalEngine(reranker=CrossEncoderReranker())
        results = await engine.retrieve(
            session=session,
            query="OpenTelemetry tracing setup",
            requester_identity="user@example.com",
            top_k=5,
        )

        assert len(results) >= 1
        assert results[0].rerank_score is not None
