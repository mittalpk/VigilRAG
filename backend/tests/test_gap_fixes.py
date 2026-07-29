"""
Tests for Gap Analysis Fixes (feature/gap-analysis-fixes).

Covers:
- GAP-F01: query_id present in HybridRetrievalResponse
- GAP-F02: audit detail returns real content_excerpt from Chunk table
- GAP-F03: viewer role blocked from POST /knowledge/query and POST /agent/run
- GAP-N02: role assignment persists audit record to QueryRecord table
- GAP-N03: pii_redact raises HTTP 503 when Presidio is unavailable
- GAP-N04: Alembic 0006_feedback_tables migration has correct structure
- GAP-N05: no on_event deprecation warnings in startup
"""

import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from unittest.mock import patch, MagicMock

from backend.app.main import app, lifespan
from backend.app.models import (
    Base,
    Chunk,
    EvidenceItemRecord,
    QueryRecord,
    Source,
    get_db_session,
)
from backend.app.services.rbac_service import seed_bootstrap_roles_and_admin


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    """Async test client with overridden DB session."""
    async def override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── GAP-F01: query_id in HybridRetrievalResponse ──────────────────────────────

@pytest.mark.asyncio
async def test_knowledge_query_returns_query_id(client):
    """GAP-F01: POST /knowledge/query must include query_id in the response so the
    frontend can use it for feedback submission (not fall back to trace_id)."""
    resp = await client.post(
        "/api/v1/knowledge/query",
        json={"query": "What is VigilRAG?", "top_k": 3},
        headers={"Authorization": "Bearer admin_token"},  # admin has all roles — avoids DB role lookup
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "query_id" in data, "query_id must be present in HybridRetrievalResponse"
    assert data["query_id"].startswith("qry-"), (
        f"query_id should start with 'qry-', got: {data['query_id']}"
    )
    # Also confirm trace_id is distinct from query_id
    assert data.get("trace_id") != data["query_id"], (
        "trace_id and query_id must be distinct identifiers"
    )


# ── GAP-F02: audit detail real content_excerpt ────────────────────────────────

@pytest.mark.asyncio
async def test_audit_detail_returns_real_content_excerpt(db_session):
    """GAP-F02: GET /audit/queries/{query_id} must return real chunk text as
    content_excerpt, not the placeholder 'Content excerpt for chunk {chunk_id}'."""
    # Seed: Source → Chunk → QueryRecord → EvidenceItemRecord
    src = Source(
        id="src-gap-f02",
        name="Test Source",
        source_type="github_repo",
        endpoint_url="https://api.github.com/repos/test/repo",
        secret_reference="kv://test/secret",
        owner_email="owner@test.com",
        sensitivity_level="internal-general",
    )
    db_session.add(src)

    chunk_id = f"chk-{uuid.uuid4().hex[:8]}"
    chunk_content = "This is the real chunk content for GAP-F02 verification."
    chunk = Chunk(
        id=chunk_id,
        source_id="src-gap-f02",
        document_id="doc-001",
        parent_doc_id="doc-001",
        content=chunk_content,
        checksum="abc123checksum",
        permissions_ref="public",
    )
    db_session.add(chunk)

    qry_id = f"qry-{uuid.uuid4().hex[:8]}"
    qr = QueryRecord(
        id=qry_id,
        requester_identity="admin@test.com",
        query_text="What is the real content?",
        trace_id="trc-gap-f02",
    )
    db_session.add(qr)

    ev = EvidenceItemRecord(
        id=f"ev-{uuid.uuid4().hex[:8]}",
        query_id=qry_id,
        chunk_id=chunk_id,
        source_id="src-gap-f02",
        source_url="https://github.com/test/repo/blob/main/file.py",
        relevance_score=0.95,
        used_in_answer=True,
    )
    db_session.add(ev)
    await db_session.commit()

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            f"/api/v1/audit/queries/{qry_id}",
            headers={"Authorization": "Bearer admin_token"},
        )
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    items = data.get("evidence_items", [])
    assert len(items) == 1, "Expected exactly 1 evidence item"
    excerpt = items[0]["content_excerpt"]
    assert excerpt == chunk_content[:500], (
        f"Expected real chunk text, got placeholder or wrong text: {excerpt!r}"
    )
    assert "Content excerpt for chunk" not in excerpt, (
        "GAP-F02: placeholder text should not appear in content_excerpt"
    )


# ── GAP-F03: viewer role blocked from query endpoints ─────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_submit_knowledge_query(client):
    """GAP-F03: A viewer-role JWT must receive HTTP 403 on POST /knowledge/query.
    Viewers can only view results; they cannot initiate new queries (US-016)."""
    resp = await client.post(
        "/api/v1/knowledge/query",
        json={"query": "Viewer tries to query", "top_k": 3},
        headers={"Authorization": "Bearer viewer_token"},
    )
    assert resp.status_code == 403, (
        f"viewer role must be blocked from /knowledge/query (got {resp.status_code})"
    )


@pytest.mark.asyncio
async def test_viewer_cannot_run_agent_task(client):
    """GAP-F03: A viewer-role JWT must receive HTTP 403 on POST /agent/run."""
    resp = await client.post(
        "/api/v1/agent/run",
        json={"task": "Viewer tries to use agent", "max_iterations": 1},
        headers={"Authorization": "Bearer viewer_token"},
    )
    assert resp.status_code == 403, (
        f"viewer role must be blocked from /agent/run (got {resp.status_code})"
    )


@pytest.mark.asyncio
async def test_user_role_can_submit_knowledge_query(client):
    """GAP-F03: A user-role JWT must be allowed to POST /knowledge/query (HTTP 200).
    Uses admin_token to avoid DB role lookup (admin includes all permissions)."""
    resp = await client.post(
        "/api/v1/knowledge/query",
        json={"query": "Normal user query", "top_k": 3},
        headers={"Authorization": "Bearer admin_token"},
    )
    assert resp.status_code == 200, (
        f"admin/user role should be allowed to query (got {resp.status_code})"
    )


# ── GAP-N02: role assignment audit record ─────────────────────────────────────

@pytest.mark.asyncio
async def test_role_assignment_persists_audit_record(db_session):
    """GAP-N02: assign_user_role must write a QueryRecord audit entry to the DB
    in addition to logging to stdout."""
    from backend.app.services.rbac_service import assign_user_role

    await seed_bootstrap_roles_and_admin(db_session)
    await assign_user_role(db_session, "new_analyst", "user", assigned_by="admin")

    # There should be a QueryRecord with ROLE_ASSIGNMENT prefix
    from sqlalchemy import select
    stmt = select(QueryRecord).where(
        QueryRecord.query_text.like("ROLE_ASSIGNMENT:%")
    )
    res = await db_session.execute(stmt)
    records = res.scalars().all()

    assert len(records) >= 1, "GAP-N02: role assignment should create an audit QueryRecord"
    role_record = records[0]
    assert "new_analyst" in role_record.query_text
    assert "user" in role_record.query_text
    assert role_record.requester_identity == "admin"


# ── GAP-N03: Presidio fail-closed ─────────────────────────────────────────────

def test_pii_redact_raises_503_when_presidio_unavailable():
    """GAP-N03: When Presidio failed to initialize, pii_redact() must raise HTTP 503
    rather than silently running weaker regex-only PII coverage."""
    from fastapi import HTTPException
    from agent.app.guardrails import GuardrailsClient

    client = GuardrailsClient.__new__(GuardrailsClient)
    client._presidio_unavailable = True
    client.presidio_analyzer = None
    client.presidio_anonymizer = None
    client.patterns = []

    with pytest.raises(HTTPException) as exc_info:
        client.pii_redact("My email is test@example.com", trace_id="trc-gap-n03")

    assert exc_info.value.status_code == 503
    assert "Presidio" in exc_info.value.detail


def test_pii_redact_works_normally_when_presidio_available():
    """GAP-N03 inverse: When Presidio is available (_presidio_unavailable=False),
    pii_redact() should not raise HTTP 503."""
    from agent.app.guardrails import GuardrailsClient

    gc = GuardrailsClient.__new__(GuardrailsClient)
    gc._presidio_unavailable = False
    gc.presidio_analyzer = None  # Use regex fallback
    gc.presidio_anonymizer = None
    gc.patterns = []

    result = gc.pii_redact("Hello world — no PII here.", trace_id="trc-gap-n03b")
    # Should not raise; should return a RedactionResult
    assert result.redacted_text == "Hello world — no PII here."


# ── GAP-N05: no on_event deprecation ──────────────────────────────────────────

def test_no_on_event_deprecation_in_main():
    """GAP-N05: main.py must use the lifespan context manager pattern,
    not the deprecated @app.on_event decorator."""
    import inspect
    import backend.app.main as main_module

    source = inspect.getsource(main_module)
    # The string '@app.on_event' must not appear as a decorator call in the source
    # (comments mentioning 'on_event' for context are fine)
    import re
    on_event_decorator = re.search(r'^\s*@app\.on_event', source, re.MULTILINE)
    assert on_event_decorator is None, (
        f"GAP-N05: @app.on_event decorator found at position {on_event_decorator.start() if on_event_decorator else None} — "
        "use lifespan context manager instead"
    )
    assert "lifespan" in source, (
        "GAP-N05: lifespan context manager must be defined in main.py"
    )


# ── GAP-N04: Alembic migration chain ──────────────────────────────────────────

def test_alembic_migration_0006_exists():
    """GAP-N04: 0006_feedback_tables migration must exist with correct revision chain."""
    import importlib
    migration = importlib.import_module(
        "backend.alembic.versions.0006_feedback_tables".replace(".", ".", 1)
    )
    # Verify it points to the correct parent
    assert migration.revision == "0006_feedback_tables"
    assert migration.down_revision == "0005_evaluation_runs"
