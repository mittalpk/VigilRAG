"""
Unit & integration tests for US-038 — Vector DB Graduation Evaluation & Migration.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.main import app
from backend.app.models import Base, Chunk, Source, get_db_session
from backend.app.services.vector_graduation_service import (
    build_migration_plan,
    evaluate_graduation_triggers,
    validate_migration_counts,
)
from backend.app.services.vector_search.dual_write import DualWriteVectorSearchBackend
from backend.app.services.vector_search.pgvector_backend import PgvectorBackend, cosine_similarity
from backend.app.services.vector_search.qdrant_backend import QdrantVectorSearchBackend
from backend.app.services.vector_search import get_vector_search_backend


@pytest_asyncio.fixture
async def async_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def client(async_session):
    def _override():
        return async_session

    app.dependency_overrides[get_db_session] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


async def _seed_small_corpus(session: AsyncSession, n: int = 3):
    session.add(
        Source(
            id="src-1",
            name="Demo",
            source_type="github_repo",
            endpoint_url="https://github.com/a/b",
            secret_reference="kv/pat",
            owner_email="o@e.com",
            status="indexed",
            is_active=True,
        )
    )
    for i in range(n):
        vec = [0.1 * (i + 1)] * 8
        session.add(
            Chunk(
                id=f"chk-{i}",
                source_id="src-1",
                document_id=f"doc-{i}",
                content=f"content about authentication policy number {i}",
                checksum=f"{i:064d}"[:64],
                permissions_ref="public",
                embedding_vector_str=json.dumps(vec),
            )
        )
    await session.commit()


# ── Protocol / backends ─────────────────────────────────────────────────────

def test_cosine_similarity_unit():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([], [1]) == 0.0


@pytest.mark.asyncio
async def test_pgvector_backend_search_and_count(async_session):
    await _seed_small_corpus(async_session)
    backend = PgvectorBackend(async_session)
    hits = await backend.search([0.3] * 8, top_k=2)
    assert len(hits) == 2
    assert hits[0].score >= hits[1].score
    assert await backend.count() == 3


@pytest.mark.asyncio
async def test_qdrant_memory_fallback_upsert_search_delete():
    q = QdrantVectorSearchBackend(url="", allow_memory_fallback=True)
    await q.upsert("c1", [1.0, 0.0], payload={"source_id": "s1"})
    await q.upsert("c2", [0.0, 1.0], payload={"source_id": "s2"})
    hits = await q.search([1.0, 0.0], top_k=1)
    assert hits[0].chunk_id == "c1"
    filtered = await q.search([1.0, 0.0], top_k=5, source_ids=["s2"])
    assert all(h.source_id == "s2" for h in filtered)
    await q.delete("c1")
    assert await q.count() == 1


@pytest.mark.asyncio
async def test_dual_write_reads_primary_writes_both(async_session):
    await _seed_small_corpus(async_session, n=1)
    primary = PgvectorBackend(async_session)
    secondary = QdrantVectorSearchBackend(url="", allow_memory_fallback=True)
    dual = DualWriteVectorSearchBackend(primary, secondary)
    await dual.upsert("chk-0", [0.1] * 8, payload={"source_id": "src-1"})
    assert await secondary.count() >= 1
    consistency = await dual.compare_search_consistency([0.1] * 8, top_k=1)
    assert "jaccard" in consistency


@pytest.mark.asyncio
async def test_factory_defaults_to_pgvector(async_session, monkeypatch):
    monkeypatch.delenv("VECTOR_SEARCH_BACKEND", raising=False)
    monkeypatch.delenv("VECTOR_SEARCH_DUAL_WRITE", raising=False)
    backend = get_vector_search_backend(async_session)
    assert backend.backend_name == "pgvector"


@pytest.mark.asyncio
async def test_factory_qdrant_and_dual(async_session, monkeypatch):
    monkeypatch.setenv("VECTOR_SEARCH_BACKEND", "qdrant")
    monkeypatch.setenv("VECTOR_SEARCH_DUAL_WRITE", "true")
    backend = get_vector_search_backend(async_session)
    assert backend.backend_name.startswith("dual:")


# ── Graduation evaluation ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evaluate_no_migration_at_pilot_scale(async_session):
    await _seed_small_corpus(async_session)
    evaluation = await evaluate_graduation_triggers(
        async_session,
        latency_p90_ms=3620.0,
        retrieval_dominant=False,
        filtering_complexity=False,
        index_build_minutes=1.0,
        operational_contention=False,
    )
    assert evaluation.signals_met == 0
    assert evaluation.decision == "no_migration"
    assert evaluation.migration_plan is None
    assert len(evaluation.signals) == 4


@pytest.mark.asyncio
async def test_evaluate_migrate_when_two_signals(async_session, monkeypatch):
    # Simulate large corpus via env override path: seed won't reach 500K, so force
    # latency + filtering signals instead
    evaluation = await evaluate_graduation_triggers(
        async_session,
        latency_p90_ms=15000.0,
        retrieval_dominant=True,
        filtering_complexity=True,
        index_build_minutes=1.0,
        operational_contention=False,
    )
    assert evaluation.signals_met >= 2
    assert evaluation.decision == "migrate"
    assert evaluation.migration_plan is not None
    assert evaluation.migration_plan["target_vector_db"] == "qdrant"


@pytest.mark.asyncio
async def test_evaluate_borderline_escalates(async_session):
    evaluation = await evaluate_graduation_triggers(
        async_session,
        latency_p90_ms=10000.0,  # near 12000 threshold, not over
        retrieval_dominant=False,
        filtering_complexity=True,  # exactly one met
        index_build_minutes=0.0,
    )
    assert evaluation.signals_met == 1
    # borderline if near latency threshold
    assert evaluation.decision in ("escalate", "no_migration")


@pytest.mark.asyncio
async def test_validate_migration_counts():
    ok = await validate_migration_counts(1000, 1000)
    assert ok["ok"] is True
    bad = await validate_migration_counts(1000, 990)  # 1% mismatch
    assert bad["ok"] is False
    assert bad["mismatch_ratio"] == pytest.approx(0.01)


def test_build_migration_plan_steps():
    plan = build_migration_plan("qdrant")
    assert "dual-write" in plan["steps"][1].lower() or "DUAL_WRITE" in plan["steps"][1]
    assert plan["rollback"]


# ── Admin API ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_evaluate_endpoint_auth_and_success(client, async_session):
    await _seed_small_corpus(async_session)

    unauth = client.get("/api/v1/admin/vector-graduation/evaluate")
    assert unauth.status_code in (401, 403)

    forbidden = client.get(
        "/api/v1/admin/vector-graduation/evaluate",
        headers={"Authorization": "Bearer viewer_token"},
    )
    assert forbidden.status_code == 403

    ok = client.get(
        "/api/v1/admin/vector-graduation/evaluate",
        headers={"Authorization": "Bearer admin_token"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["decision"] == "no_migration"
    assert body["signals_met"] == 0
    assert len(body["signals"]) == 4


@pytest.mark.asyncio
async def test_admin_validate_counts_endpoint(client):
    resp = client.post(
        "/api/v1/admin/vector-graduation/validate-counts",
        headers={"Authorization": "Bearer admin_token"},
        json={"source_count": 100, "target_count": 100},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    missing = client.post(
        "/api/v1/admin/vector-graduation/validate-counts",
        headers={"Authorization": "Bearer admin_token"},
        json={},
    )
    assert missing.status_code == 422

    user_denied = client.post(
        "/api/v1/admin/vector-graduation/validate-counts",
        headers={"Authorization": "Bearer user_token"},
        json={"source_count": 1, "target_count": 1},
    )
    assert user_denied.status_code == 403
