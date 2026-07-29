"""
Unit & Integration Tests for Feedback Routing & Review Queue Router (US-020 / FEAT-09).
"""

import json
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.main import app
from backend.app.models import (
    AnswerRecord,
    Base,
    EvaluationCase,
    FeedbackRecord,
    FeedbackReviewItem,
    QueryRecord,
    get_db_session,
)
from backend.app.services.feedback_routing_service import route_negative_feedback
from backend.app.services.rbac_service import seed_bootstrap_roles_and_admin


@pytest_asyncio.fixture
async def fbr_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await seed_bootstrap_roles_and_admin(session)

        # Query 1 (Negative Feedback)
        q1 = QueryRecord(
            id="qry-route-001",
            requester_identity="user1@example.com",
            query_text="What is the password reset procedure?",
            trace_id="trc-route-001",
        )
        session.add(q1)

        ans1 = AnswerRecord(
            id="ans-route-001",
            query_id="qry-route-001",
            answer_text="Outdated password reset policy steps.",
            trace_id="trc-route-001",
        )
        session.add(ans1)

        fb1 = FeedbackRecord(
            id="fbk-route-001",
            query_id="qry-route-001",
            requester_identity="user1@example.com",
            rating="negative",
            comment="This policy was updated last month! Steps are wrong.",
        )
        session.add(fb1)

        # Query 2 (Positive Feedback)
        q2 = QueryRecord(
            id="qry-route-002",
            requester_identity="user2@example.com",
            query_text="Where are the API docs?",
            trace_id="trc-route-002",
        )
        session.add(q2)

        fb2 = FeedbackRecord(
            id="fbk-route-002",
            query_id="qry-route-002",
            requester_identity="user2@example.com",
            rating="positive",
            comment="Great docs!",
        )
        session.add(fb2)

        await session.commit()
        yield session

    await engine.dispose()


@pytest.fixture
def fbr_client(fbr_session):
    def _get_db_override():
        return fbr_session

    app.dependency_overrides[get_db_session] = _get_db_override
    yield fbr_session
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_route_negative_feedback_service(fbr_session):
    count = await route_negative_feedback(fbr_session)
    assert count == 1

    # Verify FeedbackReviewItem in DB
    stmt = select(FeedbackReviewItem).where(FeedbackReviewItem.query_id == "qry-route-001")
    res = await fbr_session.execute(stmt)
    item = res.scalar_one_or_none()
    assert item is not None
    assert item.status == "pending"
    assert item.feedback_id == "fbk-route-001"


@pytest.mark.asyncio
async def test_list_feedback_review_queue_and_actions(fbr_client):
    admin_headers = {"Authorization": "Bearer admin_token"}

    # Execute routing job first
    await route_negative_feedback(fbr_client)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. GET queue
        res_get = await client.get("/api/v1/admin/feedback-review", headers=admin_headers)
        assert res_get.status_code == 200
        data = res_get.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["query_id"] == "qry-route-001"
        assert item["user_comment"] == "This policy was updated last month! Steps are wrong."
        assert item["status"] == "pending"

        # 2. Promote item with golden answer
        action_payload = {
            "action": "promote",
            "golden_answer": "Go to auth portal -> Security Settings -> Reset Password.",
        }
        res_act = await client.post(
            f"/api/v1/admin/feedback-review/{item['id']}/action",
            json=action_payload,
            headers=admin_headers,
        )
        assert res_act.status_code == 200
        assert res_act.json()["status"] == "promoted"

    # Verify EvaluationCase creation in DB
    stmt_case = select(EvaluationCase).where(EvaluationCase.source_type == "user_feedback")
    res_case = await fbr_client.execute(stmt_case)
    case_rec = res_case.scalar_one_or_none()
    assert case_rec is not None
    assert case_rec.query == "What is the password reset procedure?"
    assert case_rec.expected_answer == "Go to auth portal -> Security Settings -> Reset Password."
    assert "promoted" in json.loads(case_rec.tags_json)


@pytest.mark.asyncio
async def test_action_dismiss_and_investigate(fbr_client):
    admin_headers = {"Authorization": "Bearer admin_token"}
    await route_negative_feedback(fbr_client)

    stmt = select(FeedbackReviewItem).where(FeedbackReviewItem.query_id == "qry-route-001")
    res = await fbr_client.execute(stmt)
    item = res.scalar_one()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Dismiss
        res_dis = await client.post(
            f"/api/v1/admin/feedback-review/{item.id}/action",
            json={"action": "dismiss"},
            headers=admin_headers,
        )
        assert res_dis.status_code == 200
        assert res_dis.json()["status"] == "dismissed"


@pytest.mark.asyncio
async def test_feedback_review_endpoints_admin_only(fbr_client):
    user_headers = {"Authorization": "Bearer user_token"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res1 = await client.get("/api/v1/admin/feedback-review", headers=user_headers)
        assert res1.status_code == 403

        res2 = await client.post(
            "/api/v1/admin/feedback-review/fbr-test/action",
            json={"action": "dismiss"},
            headers=user_headers,
        )
        assert res2.status_code == 403
