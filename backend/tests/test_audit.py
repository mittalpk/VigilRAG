"""
Unit & Integration Tests for Compliance Audit Log Router (US-018 / FEAT-08).
"""

import json
from datetime import datetime, timedelta
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.main import app
from backend.app.models import (
    AnswerRecord,
    Base,
    EvidenceItemRecord,
    QueryRecord,
    get_db_session,
)
from backend.app.services.rbac_service import seed_bootstrap_roles_and_admin


@pytest_asyncio.fixture
async def audit_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await seed_bootstrap_roles_and_admin(session)
        
        # Seed Query 1 (alice)
        q1 = QueryRecord(
            id="qry-audit-001",
            requester_identity="alice@example.com",
            query_text="What is the internal encryption policy?",
            trace_id="trc-audit-001",
            created_at=datetime.now() - timedelta(days=2),
        )
        session.add(q1)

        ans1 = AnswerRecord(
            id="ans-audit-001",
            query_id="qry-audit-001",
            answer_text="All data must be encrypted using AES-256.",
            groundedness_score=0.95,
            guardrail_flags_json=json.dumps(["pii-redacted:EMAIL"]),
            trace_id="trc-audit-001",
        )
        session.add(ans1)

        for i in range(5):
            ev = EvidenceItemRecord(
                id=f"ev-001-{i}",
                query_id="qry-audit-001",
                chunk_id=f"chk-policy-{i}",
                source_id="src-sec-01",
                source_url=f"https://wiki.example.com/sec/policy-{i}",
                relevance_score=0.9,
                used_in_answer=True,
            )
            session.add(ev)

        # Seed Query 2 (bob - truncated evidence > 50)
        q2 = QueryRecord(
            id="qry-audit-002",
            requester_identity="bob@example.com",
            query_text="List all server configurations.",
            trace_id="trc-audit-002",
            created_at=datetime.now() - timedelta(hours=5),
        )
        session.add(q2)

        ans2 = AnswerRecord(
            id="ans-audit-002",
            query_id="qry-audit-002",
            answer_text="Here are the server configurations.",
            groundedness_score=0.88,
            guardrail_flags_json="[]",
            trace_id="trc-audit-002",
        )
        session.add(ans2)

        for i in range(60):
            ev = EvidenceItemRecord(
                id=f"ev-002-{i}",
                query_id="qry-audit-002",
                chunk_id=f"chk-config-{i}",
                source_id="src-ops-01",
                source_url=f"https://wiki.example.com/ops/config-{i}",
                relevance_score=0.8,
                used_in_answer=True,
            )
            session.add(ev)

        await session.commit()
        yield session

    await engine.dispose()


@pytest.fixture
def audit_client(audit_session):
    def _get_db_override():
        return audit_session

    app.dependency_overrides[get_db_session] = _get_db_override
    yield audit_session
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_audit_queries_success_and_filtering(audit_client):
    admin_headers = {"Authorization": "Bearer admin_token"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # All queries
        res = await client.get("/api/v1/audit/queries", headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 2
        assert data["page"] == 1
        assert data["per_page"] == 50

        # Filter by identity "alice"
        res_alice = await client.get("/api/v1/audit/queries?identity=alice", headers=admin_headers)
        assert res_alice.status_code == 200
        data_alice = res_alice.json()
        assert data_alice["total"] == 1
        assert data_alice["items"][0]["requester_identity"] == "alice@example.com"
        assert "pii-redacted:EMAIL" in data_alice["items"][0]["guardrail_flags"]


@pytest.mark.asyncio
async def test_get_audit_query_detail_and_truncation(audit_client):
    admin_headers = {"Authorization": "Bearer admin_token"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Detail for Query 1
        res1 = await client.get("/api/v1/audit/queries/qry-audit-001", headers=admin_headers)
        assert res1.status_code == 200
        d1 = res1.json()
        assert d1["query_id"] == "qry-audit-001"
        assert d1["requester_identity"] == "alice@example.com"
        assert len(d1["evidence_items"]) == 5
        assert d1["truncated"] is False

        # Detail for Query 2 (60 evidence items, capped at 50)
        res2 = await client.get("/api/v1/audit/queries/qry-audit-002", headers=admin_headers)
        assert res2.status_code == 200
        d2 = res2.json()
        assert d2["query_id"] == "qry-audit-002"
        assert len(d2["evidence_items"]) == 50
        assert d2["truncated"] is True


@pytest.mark.asyncio
async def test_audit_query_detail_not_found(audit_client):
    admin_headers = {"Authorization": "Bearer admin_token"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/audit/queries/nonexistent-query-999", headers=admin_headers)
        assert res.status_code == 404
        assert "not found" in res.json()["detail"]


@pytest.mark.asyncio
async def test_audit_endpoints_admin_only_403_and_401(audit_client):
    user_headers = {"Authorization": "Bearer user_token"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Non-admin user receives 403
        res1 = await client.get("/api/v1/audit/queries", headers=user_headers)
        assert res1.status_code == 403

        res2 = await client.get("/api/v1/audit/queries/qry-audit-001", headers=user_headers)
        assert res2.status_code == 403

        # Unauthenticated receives 401 or 403
        res3 = await client.get("/api/v1/audit/queries")
        assert res3.status_code in (401, 403)
