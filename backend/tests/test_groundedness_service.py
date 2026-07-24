"""
Test suite for US-013 EvidenceItem Entity & Groundedness Score Tracking.
Tests:
- calculate_groundedness_and_used_chunks calculation logic (full, partial, zero, empty evidence).
- Async DB persistence of QueryRecord, EvidenceItemRecord[], and AnswerRecord.
- Graceful fail-safe handling on DB persistence errors.
"""

import json
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from unittest.mock import AsyncMock

from backend.app.models import AnswerRecord, Base, EvidenceItemRecord, QueryRecord
from backend.app.services.groundedness_service import (
    calculate_groundedness_and_used_chunks,
    persist_query_evidence_answer,
)


@pytest_asyncio.fixture
async def test_async_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def test_calculate_groundedness_full():
    evidence = [
        {"chunk_id": "c1", "content": "JWT authentication uses HS256 algorithm for signature verification."},
        {"chunk_id": "c2", "content": "Database passwords are stored in Azure Key Vault secret references."},
    ]
    answer = "JWT authentication uses HS256 algorithm. Database passwords are stored in Azure Key Vault secret references."

    score, processed = calculate_groundedness_and_used_chunks(evidence, answer)
    assert score == 1.0
    assert processed[0]["used_in_answer"] is True
    assert processed[1]["used_in_answer"] is True


def test_calculate_groundedness_partial():
    evidence = [
        {"chunk_id": "c1", "content": "JWT authentication uses HS256 algorithm for signature verification."},
        {"chunk_id": "c2", "content": "Unused legacy OAuth1 protocol parameters documentation."},
    ]
    answer = "JWT authentication uses HS256 algorithm for signature verification."

    score, processed = calculate_groundedness_and_used_chunks(evidence, answer)
    assert score == 0.5
    assert processed[0]["used_in_answer"] is True
    assert processed[1]["used_in_answer"] is False


def test_calculate_groundedness_zero():
    evidence = [
        {"chunk_id": "c1", "content": "Completely unrelated documentation on database indexing."},
        {"chunk_id": "c2", "content": "Legacy cache eviction strategies."},
    ]
    answer = "The system employs OAuth2 bearer tokens for user authorization."

    score, processed = calculate_groundedness_and_used_chunks(evidence, answer)
    assert score == 0.0
    assert processed[0]["used_in_answer"] is False
    assert processed[1]["used_in_answer"] is False


def test_calculate_groundedness_empty_evidence():
    score, processed = calculate_groundedness_and_used_chunks([], "Some answer text.")
    assert score is None
    assert processed == []


@pytest.mark.asyncio
async def test_persist_query_evidence_answer_success(test_async_session):
    query_id = "qry-test-100"
    trace_id = "trc-test-100"
    requester = "alice@example.com"
    query_text = "How does authentication work?"
    evidence = [
        {
            "chunk_id": "chk-001",
            "source_id": "github-repo",
            "source_url": "https://github.com/org/repo/blob/main/auth.py",
            "relevance_score": 0.92,
            "content": "def verify_jwt(): pass",
        }
    ]
    answer_text = "Authentication uses verify_jwt function."

    success = await persist_query_evidence_answer(
        session=test_async_session,
        query_id=query_id,
        requester_identity=requester,
        query_text=query_text,
        trace_id=trace_id,
        evidence_items=evidence,
        answer_text=answer_text,
        guardrail_flags=["pii-redacted"],
    )
    assert success is True

    # Verify QueryRecord
    q_res = await test_async_session.execute(select(QueryRecord).where(QueryRecord.id == query_id))
    q_rec = q_res.scalar_one_or_none()
    assert q_rec is not None
    assert q_rec.requester_identity == requester
    assert q_rec.trace_id == trace_id

    # Verify EvidenceItemRecord
    ev_res = await test_async_session.execute(select(EvidenceItemRecord).where(EvidenceItemRecord.query_id == query_id))
    ev_recs = ev_res.scalars().all()
    assert len(ev_recs) == 1
    assert ev_recs[0].chunk_id == "chk-001"
    assert ev_recs[0].used_in_answer is True

    # Verify AnswerRecord
    ans_res = await test_async_session.execute(select(AnswerRecord).where(AnswerRecord.query_id == query_id))
    ans_rec = ans_res.scalar_one_or_none()
    assert ans_rec is not None
    assert ans_rec.groundedness_score == 1.0
    assert "pii-redacted" in ans_rec.guardrail_flags_json


@pytest.mark.asyncio
async def test_persist_query_evidence_answer_graceful_error_handling():
    mock_session = AsyncMock()
    mock_session.commit.side_effect = Exception("Database connection failure")

    success = await persist_query_evidence_answer(
        session=mock_session,
        query_id="qry-err-1",
        requester_identity="bob@example.com",
        query_text="Sample query",
        trace_id="trc-err-1",
        evidence_items=[],
        answer_text="Sample answer",
    )
    # Fail-safe: returns False without throwing exception
    assert success is False
    assert mock_session.rollback.called
