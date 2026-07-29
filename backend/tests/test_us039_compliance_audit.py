"""
Unit & integration tests for US-039 compliance-grade audit capabilities.

Covers retention archival, export TTL, FTS (?q=), digest, and 401/403/422 edges.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.main import app
from backend.app.models import (
    AnswerRecord,
    ArchivedQuery,
    Base,
    EvidenceItemRecord,
    QueryRecord,
    RetentionRun,
    get_db_session,
)
from backend.app.services.audit_digest_service import compute_digest_stats, send_audit_digest
from backend.app.services.audit_export_service import create_audit_export, get_export_for_download
from backend.app.services.audit_retention_service import enforce_audit_retention
from backend.app.services.rbac_service import seed_bootstrap_roles_and_admin


@pytest_asyncio.fixture
async def us039_session(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("AUDIT_EXPORT_TTL_SECONDS", "3600")
    monkeypatch.setenv("AUDIT_EXPORT_ASYNC_THRESHOLD", "10000")
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "30")
    monkeypatch.setenv("AUDIT_DIGEST_CHANNEL", "log")
    monkeypatch.setenv("AUDIT_DIGEST_AUTO_SEED", "true")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await seed_bootstrap_roles_and_admin(session)

        now = datetime.now(timezone.utc)
        # Fresh query (within retention)
        session.add(
            QueryRecord(
                id="qry-fresh-001",
                requester_identity="alice@example.com",
                query_text="What is the encryption policy for regulated data?",
                trace_id="trc-fresh-001",
                created_at=now - timedelta(days=2),
            )
        )
        session.add(
            AnswerRecord(
                id="ans-fresh-001",
                query_id="qry-fresh-001",
                answer_text="AES-256 at rest; TLS in transit.",
                groundedness_score=0.94,
                guardrail_flags_json=json.dumps(["pii-redacted:EMAIL"]),
                trace_id="trc-fresh-001",
            )
        )
        session.add(
            EvidenceItemRecord(
                id="ev-fresh-001",
                query_id="qry-fresh-001",
                chunk_id="chk-sec-1",
                source_id="src-sec",
                source_url="https://wiki.example.com/sec/encryption",
                relevance_score=0.91,
                used_in_answer=True,
            )
        )

        # Old query (beyond retention)
        session.add(
            QueryRecord(
                id="qry-old-001",
                requester_identity="bob@example.com",
                query_text="Obsolete server inventory dump",
                trace_id="trc-old-001",
                created_at=now - timedelta(days=90),
            )
        )
        session.add(
            AnswerRecord(
                id="ans-old-001",
                query_id="qry-old-001",
                answer_text="Deprecated inventory.",
                groundedness_score=0.5,
                guardrail_flags_json="[]",
                trace_id="trc-old-001",
            )
        )
        session.add(
            EvidenceItemRecord(
                id="ev-old-001",
                query_id="qry-old-001",
                chunk_id="chk-ops-1",
                source_id="src-ops",
                source_url="https://wiki.example.com/ops/inventory",
                relevance_score=0.7,
                used_in_answer=True,
            )
        )

        await session.commit()
        yield session

    await engine.dispose()


@pytest.fixture
def us039_client(us039_session):
    async def _override():
        yield us039_session

    app.dependency_overrides[get_db_session] = _override
    yield us039_session
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_retention_archives_then_deletes(us039_session):
    result = await enforce_audit_retention(us039_session, retention_days=30, batch_size=10)
    assert result["status"] == "success"
    assert result["records_archived"] == 1

    archived = (
        await us039_session.execute(select(ArchivedQuery).where(ArchivedQuery.id == "qry-old-001"))
    ).scalar_one_or_none()
    assert archived is not None
    assert archived.requester_identity == "bob@example.com"
    assert "inventory" in archived.query_text.lower()
    evidence = json.loads(archived.evidence_json)
    assert len(evidence) == 1

    remaining_old = (
        await us039_session.execute(select(QueryRecord).where(QueryRecord.id == "qry-old-001"))
    ).scalar_one_or_none()
    assert remaining_old is None

    # Cascade deleted evidence/answer for archived query
    ev = (
        await us039_session.execute(
            select(EvidenceItemRecord).where(EvidenceItemRecord.query_id == "qry-old-001")
        )
    ).scalar_one_or_none()
    assert ev is None

    # Fresh query retained
    fresh = (
        await us039_session.execute(select(QueryRecord).where(QueryRecord.id == "qry-fresh-001"))
    ).scalar_one()
    assert fresh is not None

    run = (
        await us039_session.execute(select(RetentionRun).where(RetentionRun.id == result["retention_run_id"]))
    ).scalar_one()
    assert run.status == "success"
    assert run.records_archived == 1


@pytest.mark.asyncio
async def test_retention_transactional_no_partial_on_failure(us039_session, monkeypatch):
    """If archival fails mid-batch, hot rows must remain and run is marked failed."""
    from backend.app.services import audit_retention_service as svc

    original_add = us039_session.add
    calls = {"n": 0}

    def flaky_add(obj):
        from backend.app.models import ArchivedQuery as AQ

        if isinstance(obj, AQ):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated archive failure")
        return original_add(obj)

    monkeypatch.setattr(us039_session, "add", flaky_add)

    result = await enforce_audit_retention(us039_session, retention_days=30, batch_size=10)
    assert result["status"] == "failed"
    assert result["records_archived"] == 0

    # Old query still present (no partial delete)
    remaining = (
        await us039_session.execute(select(QueryRecord).where(QueryRecord.id == "qry-old-001"))
    ).scalar_one_or_none()
    assert remaining is not None

    archived_count = (
        await us039_session.execute(select(ArchivedQuery))
    ).scalars().all()
    assert len(archived_count) == 0


@pytest.mark.asyncio
async def test_export_csv_and_pdf_with_ttl_download(us039_client, tmp_path, monkeypatch):
    admin = {"Authorization": "Bearer admin_token"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Missing params → 422
        missing = await client.post("/api/v1/audit/export", headers=admin)
        assert missing.status_code == 422

        # Query-param form
        today = datetime.now(timezone.utc).date().isoformat()
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        res = await client.post(
            f"/api/v1/audit/export?from={week_ago}&to={today}&format=csv",
            headers=admin,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ready"
        assert data["async"] is False
        assert data["row_count"] >= 1
        assert data["download_url"]
        assert "token=" in data["download_url"]

        token = data["download_url"].split("token=")[-1]
        export_id = data["export_id"]
        dl = await client.get(f"/api/v1/audit/exports/{export_id}/download?token={token}")
        assert dl.status_code == 200
        assert "text/csv" in dl.headers.get("content-type", "")
        assert b"query_id" in dl.content

        # Bad token → 403
        bad = await client.get(f"/api/v1/audit/exports/{export_id}/download?token=not-the-token")
        assert bad.status_code == 403

        # PDF export via JSON body
        pdf = await client.post(
            "/api/v1/audit/export",
            headers=admin,
            json={"from_date": week_ago, "to_date": today, "format": "pdf"},
        )
        assert pdf.status_code == 200
        pdf_data = pdf.json()
        pdf_token = pdf_data["download_url"].split("token=")[-1]
        pdf_dl = await client.get(
            f"/api/v1/audit/exports/{pdf_data['export_id']}/download?token={pdf_token}"
        )
        assert pdf_dl.status_code == 200
        assert pdf_dl.content[:4] == b"%PDF"

        # Expired token path (service-level)
        monkeypatch.setenv("AUDIT_EXPORT_TTL_SECONDS", "1")
        created = await create_audit_export(
            us039_client,
            requested_by="admin@example.com",
            from_date=week_ago,
            to_date=today,
            fmt="csv",
        )
        # Force expiry
        from backend.app.models import AuditExport

        exp = (
            await us039_client.execute(select(AuditExport).where(AuditExport.id == created["export_id"]))
        ).scalar_one()
        exp.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        await us039_client.flush()
        expired_token = created["download_url"].split("token=")[-1]
        with pytest.raises(PermissionError):
            await get_export_for_download(us039_client, created["export_id"], expired_token)


@pytest.mark.asyncio
async def test_export_async_202_and_meta_audit(us039_client):
    admin = {"Authorization": "Bearer admin_token"}
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/audit/export",
            headers=admin,
            json={
                "from_date": week_ago,
                "to_date": today,
                "format": "csv",
                "force_async": True,
            },
        )
        assert res.status_code == 202
        data = res.json()
        assert data["async"] is True
        assert data["download_url"]

        # Meta-audit rows present
        meta = await client.get("/api/v1/audit/queries?q=AUDIT_META", headers=admin)
        assert meta.status_code == 200
        assert meta.json()["total"] >= 1


@pytest.mark.asyncio
async def test_audit_fts_q_param(us039_client):
    admin = {"Authorization": "Bearer admin_token"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/audit/queries?q=encryption", headers=admin)
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 1
        assert any("encryption" in (i["text"] or "").lower() for i in data["items"])

        none = await client.get("/api/v1/audit/queries?q=zzzz-no-match-zzzz", headers=admin)
        assert none.status_code == 200
        assert none.json()["total"] == 0


@pytest.mark.asyncio
async def test_export_and_retention_auth_edges(us039_client):
    user = {"Authorization": "Bearer user_token"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/v1/audit/export?from=2020-01-01&to=2030-01-01", headers=user)).status_code == 403
        assert (await client.get("/api/v1/audit/retention", headers=user)).status_code == 403
        assert (await client.post("/api/v1/audit/digest", headers=user)).status_code == 403
        assert (await client.post("/api/v1/audit/export?from=2020-01-01&to=2030-01-01")).status_code in (401, 403)
        assert (await client.get("/api/v1/audit/retention")).status_code in (401, 403)


@pytest.mark.asyncio
async def test_retention_status_and_digest(us039_client):
    admin = {"Authorization": "Bearer admin_token"}
    await enforce_audit_retention(us039_client, retention_days=30)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status_res = await client.get("/api/v1/audit/retention", headers=admin)
        assert status_res.status_code == 200
        body = status_res.json()
        assert body["retention_days"] == 30
        assert body["latest_run"] is not None
        assert body["latest_run"]["status"] == "success"

        digest = await client.post("/api/v1/audit/digest?cadence=weekly", headers=admin)
        assert digest.status_code == 200
        d = digest.json()
        assert d["status"] == "sent"
        assert "query_count" in d["stats"]
        assert d["delivery"]["delivered"] is True

        bad = await client.post("/api/v1/audit/digest?cadence=yearly", headers=admin)
        assert bad.status_code == 422


@pytest.mark.asyncio
async def test_digest_service_unit(us039_session):
    stats = await compute_digest_stats(us039_session, cadence="weekly")
    assert stats["query_count"] >= 1
    assert stats["unique_identities"] >= 1
    assert stats["flagged_responses"] >= 1

    result = await send_audit_digest(us039_session, cadence="monthly", channel="log")
    assert result["status"] == "sent"
    assert "Query count" in result["markdown"]
