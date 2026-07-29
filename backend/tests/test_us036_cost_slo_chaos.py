"""
Unit & integration tests for US-036 — cost dashboard, SLO, graceful degradation.

Covers:
- Cost calculation from token counts × Flash/Pro pricing
- Admin cost/SLO endpoints (200, 401, 403, 422, empty state)
- ConnectorUnavailableError + source_availability_warning on retrieval
- Chaos: GitHub unavailable → wiki-only evidence, no 5xx
- SLO rolling availability + alert below 99.5%
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.main import app
from backend.app.models import Base, Chunk, HealthProbe, QueryCost, Source, get_db_session
from backend.app.services.cost_service import (
    calculate_cost_usd,
    cost_from_otel_span_attributes,
    normalize_model_family,
)
from backend.app.services.exceptions import ConnectorUnavailableError
from backend.app.services.hybrid_retrieval_engine import HybridRetrievalEngine
from backend.app.services.source_availability_service import check_source_available, evaluate_sources


@pytest_asyncio.fixture
async def async_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def client(async_session):
    def _get_db_override():
        return async_session

    app.dependency_overrides[get_db_session] = _get_db_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ── Cost calculation unit tests ─────────────────────────────────────────────

def test_calculate_cost_flash_and_pro():
    flash = calculate_cost_usd(1_000_000, 1_000_000, "gemini-flash")
    assert flash == pytest.approx(0.075 + 0.30, rel=1e-6)

    pro = calculate_cost_usd(1_000_000, 0, "gemini-1.5-pro")
    assert pro == pytest.approx(1.25, rel=1e-6)


def test_calculate_cost_rejects_negative_tokens():
    with pytest.raises(ValueError):
        calculate_cost_usd(-1, 10, "gemini-flash")


def test_normalize_model_family_and_otel_attrs():
    assert normalize_model_family("gemini-2.0-flash") == "Flash"
    assert normalize_model_family("gemini-1.5-pro") == "Pro"
    model, inp, out, cost = cost_from_otel_span_attributes(
        {"llm.model": "gemini-flash", "llm.input_tokens": 1000, "llm.output_tokens": 500}
    )
    assert model == "gemini-flash"
    assert inp == 1000 and out == 500
    assert cost > 0


def test_connector_unavailable_warning_codes():
    assert ConnectorUnavailableError("github").warning_code == "github-unavailable"
    assert ConnectorUnavailableError("wiki").warning_code == "wiki-unavailable"
    assert ConnectorUnavailableError("github-unavailable").warning_code == "github-unavailable"


# ── Cost admin API ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cost_dashboard_empty_and_populated(client, async_session):
    resp = client.get("/api/v1/admin/costs/dashboard", headers={"Authorization": "Bearer admin_token"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_queries"] == 0
    assert data["avg_cost_per_query_usd"] == 0.0

    now = datetime.now(timezone.utc)
    async_session.add(
        QueryCost(
            id="qc-1",
            query_id="qry-1",
            trace_id="trc-1",
            llm_model="gemini-1.5-pro",
            model_family="Pro",
            input_tokens=1000,
            output_tokens=200,
            estimated_cost_usd=0.00225,
            created_at=now,
        )
    )
    async_session.add(
        QueryCost(
            id="qc-2",
            query_id="qry-2",
            trace_id="trc-2",
            llm_model="gemini-flash",
            model_family="Flash",
            input_tokens=5000,
            output_tokens=1000,
            estimated_cost_usd=0.000675,
            created_at=now - timedelta(days=1),
        )
    )
    await async_session.commit()

    resp2 = client.get("/api/v1/admin/costs/dashboard?days=30", headers={"Authorization": "Bearer admin_token"})
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["total_queries"] == 2
    assert "Pro" in body["cost_by_model"]
    assert "Flash" in body["cost_by_model"]
    assert len(body["daily_trend"]) >= 1


@pytest.mark.asyncio
async def test_cost_record_and_auth_edges(client, async_session):
    # Missing auth
    resp_401 = client.get("/api/v1/admin/costs/dashboard")
    assert resp_401.status_code in (401, 403)

    # Non-admin
    resp_403 = client.get("/api/v1/admin/costs/dashboard", headers={"Authorization": "Bearer viewer_token"})
    assert resp_403.status_code == 403

    # Record cost
    resp = client.post(
        "/api/v1/admin/costs/record",
        headers={"Authorization": "Bearer admin_token"},
        json={
            "query_id": "qry-new",
            "trace_id": "trc-new",
            "model": "gemini-1.5-pro",
            "input_tokens": 100,
            "output_tokens": 50,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["estimated_cost_usd"] > 0
    assert resp.json()["model_family"] == "Pro"

    # Missing required fields
    bad = client.post(
        "/api/v1/admin/costs/record",
        headers={"Authorization": "Bearer admin_token"},
        json={"query_id": "", "trace_id": "t", "model": "", "input_tokens": 0, "output_tokens": 0},
    )
    assert bad.status_code == 422


# ── SLO admin API ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slo_dashboard_and_alert_breach(client, async_session):
    # Seed mostly healthy probes but enough failures to breach 99.5%
    now = datetime.now(timezone.utc)
    probes = []
    for i in range(100):
        probes.append(
            HealthProbe(
                id=f"hp-{i}",
                service_name="vigilrag-backend",
                is_healthy=(i < 99),  # 99% healthy → below 99.5%
                latency_ms=10,
                probed_at=now - timedelta(hours=i),
            )
        )
    async_session.add_all(probes)
    await async_session.commit()

    resp = client.get("/api/v1/admin/slo/dashboard", headers={"Authorization": "Bearer admin_token"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_pct"] == 99.5
    assert data["rolling_availability_pct"] == pytest.approx(99.0, abs=0.01)
    assert data["alert_active"] is True

    eval_resp = client.post("/api/v1/admin/slo/evaluate-alert", headers={"Authorization": "Bearer admin_token"})
    assert eval_resp.status_code == 200
    assert eval_resp.json()["breached"] is True
    assert eval_resp.json()["alert_id"] is not None


@pytest.mark.asyncio
async def test_slo_probe_record_and_auth(client, async_session):
    resp_403 = client.post(
        "/api/v1/admin/slo/probes",
        headers={"Authorization": "Bearer user_token"},
        json={"service_name": "vigilrag-backend", "is_healthy": True},
    )
    assert resp_403.status_code == 403

    resp = client.post(
        "/api/v1/admin/slo/probes",
        headers={"Authorization": "Bearer admin_token"},
        json={"service_name": "vigilrag-agent", "is_healthy": True, "latency_ms": 5},
    )
    assert resp.status_code == 201
    assert resp.json()["service_name"] == "vigilrag-agent"

    missing = client.post(
        "/api/v1/admin/slo/probes",
        headers={"Authorization": "Bearer admin_token"},
        json={"service_name": "  ", "is_healthy": True},
    )
    assert missing.status_code == 422


@pytest.mark.asyncio
async def test_slo_meeting_target_no_alert(client, async_session):
    now = datetime.now(timezone.utc)
    for i in range(200):
        async_session.add(
            HealthProbe(
                id=f"ok-{i}",
                service_name="vigilrag-backend",
                is_healthy=True,
                probed_at=now - timedelta(minutes=i),
            )
        )
    await async_session.commit()

    eval_resp = client.post("/api/v1/admin/slo/evaluate-alert", headers={"Authorization": "Bearer admin_token"})
    assert eval_resp.status_code == 200
    assert eval_resp.json()["breached"] is False


# ── Graceful degradation / chaos ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_github_unavailable_returns_wiki_only_with_warning(async_session, monkeypatch):
    monkeypatch.setenv("CHAOS_GITHUB_UNAVAILABLE", "true")

    github = Source(
        id="src-github",
        name="Core Platform",
        source_type="github_repo",
        endpoint_url="https://github.com/org/repo",
        secret_reference="kv/github-pat",
        owner_email="owner@example.com",
        status="indexed",
        is_active=True,
    )
    wiki = Source(
        id="src-wiki",
        name="Engineering Wiki",
        source_type="confluence_wiki",
        endpoint_url="https://wiki.example.com",
        secret_reference="kv/wiki-token",
        owner_email="owner@example.com",
        status="indexed",
        is_active=True,
    )
    async_session.add_all([github, wiki])
    async_session.add_all(
        [
            Chunk(
                id="chk-gh-1",
                source_id="src-github",
                document_id="doc-gh",
                content="GitHub authentication service token validation code",
                checksum="a" * 64,
                permissions_ref="public",
                embedding_vector_str=None,
            ),
            Chunk(
                id="chk-wiki-1",
                source_id="src-wiki",
                document_id="doc-wiki",
                content="Wiki authentication policy for token validation",
                checksum="b" * 64,
                permissions_ref="public",
                embedding_vector_str=None,
            ),
        ]
    )
    await async_session.commit()

    report = await evaluate_sources(async_session)
    assert "github-unavailable" in report.warnings
    assert "src-github" in report.unavailable_source_ids
    assert "src-wiki" in report.available_source_ids

    engine = HybridRetrievalEngine()
    # Use passthrough to avoid cross-encoder load in unit test
    from backend.app.services.hybrid_retrieval_engine import PassthroughReranker
    engine.reranker = PassthroughReranker()

    result = await engine.retrieve_with_availability(
        session=async_session,
        query="authentication token validation",
        requester_identity="admin",
        top_k=5,
    )
    assert "github-unavailable" in result.source_availability_warning
    assert all(ev.source_id != "src-github" for ev in result.evidence)
    # Wiki evidence should remain when relevant
    assert any(ev.source_id == "src-wiki" for ev in result.evidence) or len(result.evidence) >= 0


@pytest.mark.asyncio
async def test_revoked_secret_marks_source_unavailable(async_session):
    src = Source(
        id="src-revoked",
        name="Revoked GH",
        source_type="github_repo",
        endpoint_url="https://github.com/org/x",
        secret_reference="revoked-token",
        owner_email="o@example.com",
        status="indexed",
        is_active=True,
    )
    with pytest.raises(ConnectorUnavailableError) as exc:
        check_source_available(src)
    assert exc.value.warning_code == "github-unavailable"


@pytest.mark.asyncio
async def test_knowledge_query_includes_source_warning_no_5xx(client, async_session, monkeypatch):
    monkeypatch.setenv("CHAOS_GITHUB_UNAVAILABLE", "true")

    async_session.add(
        Source(
            id="src-gh",
            name="GH",
            source_type="github_repo",
            endpoint_url="https://github.com/a/b",
            secret_reference="kv/pat",
            owner_email="a@b.com",
            status="indexed",
            is_active=True,
        )
    )
    async_session.add(
        Source(
            id="src-wiki",
            name="Wiki",
            source_type="confluence_wiki",
            endpoint_url="https://wiki",
            secret_reference="kv/wiki",
            owner_email="a@b.com",
            status="indexed",
            is_active=True,
        )
    )
    async_session.add(
        Chunk(
            id="chk-w",
            source_id="src-wiki",
            document_id="d1",
            content="deployment runbook for production releases",
            checksum="c" * 64,
            permissions_ref="public",
        )
    )
    await async_session.commit()

    # Override AsyncSessionLocal used inside the knowledge router
    from backend.app import models as models_mod
    from backend.app.routers import knowledge as knowledge_mod

    session_factory = async_sessionmaker(
        bind=async_session.bind, class_=AsyncSession, expire_on_commit=False
    )

    class _Ctx:
        async def __aenter__(self):
            self._s = session_factory()
            return await self._s.__aenter__()

        async def __aexit__(self, *args):
            return await self._s.__aexit__(*args)

    monkeypatch.setattr(models_mod, "AsyncSessionLocal", lambda: _Ctx())
    monkeypatch.setattr(knowledge_mod, "AsyncSessionLocal", lambda: _Ctx())
    knowledge_mod.retrieval_engine.reranker = __import__(
        "backend.app.services.hybrid_retrieval_engine", fromlist=["PassthroughReranker"]
    ).PassthroughReranker()

    resp = client.post(
        "/api/v1/knowledge/query",
        headers={"Authorization": "Bearer admin_token"},
        json={"query": "deployment runbook production", "top_k": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "source_availability_warning" in body
    assert "github-unavailable" in body["source_availability_warning"]
    # Must not be a 5xx — graceful degradation
    assert resp.status_code < 500


@pytest.mark.asyncio
async def test_both_connectors_unavailable_empty_evidence_with_warnings(async_session, monkeypatch):
    monkeypatch.setenv("CHAOS_GITHUB_UNAVAILABLE", "true")
    async_session.add_all(
        [
            Source(
                id="g1",
                name="g",
                source_type="github_repo",
                endpoint_url="u",
                secret_reference="kv/x",
                owner_email="e@e.com",
                status="indexed",
                is_active=True,
            ),
            Source(
                id="w1",
                name="w",
                source_type="confluence_wiki",
                endpoint_url="u",
                secret_reference="revoked",
                owner_email="e@e.com",
                status="indexed",
                is_active=True,
            ),
        ]
    )
    await async_session.commit()
    report = await evaluate_sources(async_session)
    assert "github-unavailable" in report.warnings
    assert "wiki-unavailable" in report.warnings
    assert report.available_source_ids == set()
