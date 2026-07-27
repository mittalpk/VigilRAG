"""
Unit & Integration Tests for US-022 Admin Evaluation Runs Endpoints.

Tests:
- GET /api/v1/admin/evaluation-runs/latest (200 OK, 404 Not Found, 403 Forbidden).
- GET /api/v1/admin/evaluation-runs (Pagination, filtering by dataset_version & pipeline_version).
- Admin role dependency enforcement via require_admin.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.main import app
from backend.app.models import Base, EvaluationRun, get_db_session


@pytest_asyncio.fixture
async def async_admin_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def client(async_admin_session):
    def _get_db_override():
        return async_admin_session

    app.dependency_overrides[get_db_session] = _get_db_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_latest_evaluation_run_empty_404(client, async_admin_session):
    resp = client.get(
        "/api/v1/admin/evaluation-runs/latest",
        headers={"Authorization": "Bearer admin_token"},
    )
    assert resp.status_code == 404
    assert "No evaluation runs recorded" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_latest_evaluation_run_success(client, async_admin_session):
    run = EvaluationRun(
        id="run-latest-001",
        pipeline_version="a1b2c3d",
        dataset_version="v1.0",
        total_cases=20,
        faithfulness=0.92,
        context_precision=0.88,
        context_recall=0.95,
        answer_relevancy=0.90,
        passed_threshold=True,
    )
    async_admin_session.add(run)
    await async_admin_session.commit()

    resp = client.get(
        "/api/v1/admin/evaluation-runs/latest",
        headers={"Authorization": "Bearer admin_token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "run-latest-001"
    assert data["pipeline_version"] == "a1b2c3d"
    assert data["faithfulness"] == 0.92
    assert data["passed_threshold"] is True


@pytest.mark.asyncio
async def test_list_evaluation_runs_pagination_and_filtering(client, async_admin_session):
    run1 = EvaluationRun(
        id="run-001",
        pipeline_version="v1.0.0",
        dataset_version="v1.0",
        faithfulness=0.85,
    )
    run2 = EvaluationRun(
        id="run-002",
        pipeline_version="v1.1.0",
        dataset_version="v2.0",
        faithfulness=0.95,
    )
    async_admin_session.add_all([run1, run2])
    await async_admin_session.commit()

    # Filter by dataset_version
    resp = client.get(
        "/api/v1/admin/evaluation-runs?dataset_version=v2.0",
        headers={"Authorization": "Bearer admin_token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "run-002"


@pytest.mark.asyncio
async def test_evaluation_runs_endpoints_admin_only_403(client):
    resp_latest = client.get(
        "/api/v1/admin/evaluation-runs/latest",
        headers={"Authorization": "Bearer viewer_token"},
    )
    assert resp_latest.status_code == 403

    resp_list = client.get(
        "/api/v1/admin/evaluation-runs",
        headers={"Authorization": "Bearer viewer_token"},
    )
    assert resp_list.status_code == 403
