"""
Unit & Integration Tests for Thumbs Up / Down Feedback Router (US-019 / FEAT-09).
"""

import logging
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.main import app
from backend.app.models import (
    Base,
    FeedbackRecord,
    QueryRecord,
    get_db_session,
)
from backend.app.services.rbac_service import seed_bootstrap_roles_and_admin


@pytest_asyncio.fixture
async def feedback_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await seed_bootstrap_roles_and_admin(session)

        # Seed valid QueryRecord
        q1 = QueryRecord(
            id="qry-fb-001",
            requester_identity="user@example.com",
            query_text="How do I configure JWT secret key?",
            trace_id="trc-fb-001",
        )
        session.add(q1)

        await session.commit()
        yield session

    await engine.dispose()


@pytest.fixture
def feedback_client(feedback_session):
    def _get_db_override():
        return feedback_session

    app.dependency_overrides[get_db_session] = _get_db_override
    yield feedback_session
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_submit_feedback_success(feedback_client):
    headers = {"Authorization": "Bearer user_token"}
    payload = {
        "query_id": "qry-fb-001",
        "rating": "positive",
        "comment": "Very clear and helpful explanation!",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/feedback", json=payload, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["received"] is True
        assert data["query_id"] == "qry-fb-001"
        assert data["rating"] == "positive"
        assert "feedback_id" in data

    # Verify DB persistence
    stmt = select(FeedbackRecord).where(FeedbackRecord.query_id == "qry-fb-001")
    res_db = await feedback_client.execute(stmt)
    rec = res_db.scalar_one_or_none()
    assert rec is not None
    assert rec.rating == "positive"
    assert rec.comment == "Very clear and helpful explanation!"


@pytest.mark.asyncio
async def test_submit_feedback_invalid_rating_422(feedback_client):
    headers = {"Authorization": "Bearer user_token"}
    payload = {
        "query_id": "qry-fb-001",
        "rating": "invalid_rating",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/feedback", json=payload, headers=headers)
        assert res.status_code == 422
        assert "Rating must be 'positive' or 'negative'" in res.json()["detail"]


@pytest.mark.asyncio
async def test_submit_feedback_duplicate_409(feedback_client):
    headers = {"Authorization": "Bearer user_token"}
    payload = {
        "query_id": "qry-fb-001",
        "rating": "negative",
        "comment": "Needs more code examples.",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First submission
        res1 = await client.post("/api/v1/feedback", json=payload, headers=headers)
        assert res1.status_code == 200

        # Duplicate submission by same identity for same query
        res2 = await client.post("/api/v1/feedback", json=payload, headers=headers)
        assert res2.status_code == 409
        assert "already submitted" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_submit_feedback_query_not_found_404(feedback_client):
    headers = {"Authorization": "Bearer user_token"}
    payload = {
        "query_id": "nonexistent-query-id-999",
        "rating": "positive",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/feedback", json=payload, headers=headers)
        assert res.status_code == 404
        assert "not found" in res.json()["detail"]


@pytest.mark.asyncio
async def test_submit_feedback_pii_warning_logged(feedback_client, caplog):
    headers = {"Authorization": "Bearer user_token"}
    payload = {
        "query_id": "qry-fb-001",
        "rating": "negative",
        "comment": "Contact john.doe@example.com for clarifications.",
    }

    with caplog.at_level(logging.WARNING):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post("/api/v1/feedback", json=payload, headers=headers)
            assert res.status_code == 200

    assert "PII warning: Feedback comment" in caplog.text
