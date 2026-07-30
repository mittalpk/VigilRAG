"""
Unit tests for modular QueryRouter (demo-readiness / FR-001 broker).
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.models import Base
from backend.app.services.query_router import (
    GraphRetrievalEngineStub,
    QueryRouter,
    RetrievalEngineKind,
    VectorHybridEngine,
    default_query_router,
)


@pytest.mark.asyncio
async def test_query_router_resolves_auto_to_vector():
    assert default_query_router.resolve_engine("auto") == RetrievalEngineKind.VECTOR
    assert default_query_router.resolve_engine(None) == RetrievalEngineKind.VECTOR
    assert default_query_router.resolve_engine("vector") == RetrievalEngineKind.VECTOR
    assert default_query_router.resolve_engine("graph") == RetrievalEngineKind.GRAPH


@pytest.mark.asyncio
async def test_query_router_rejects_unknown_engine():
    with pytest.raises(ValueError, match="Unknown retrieval engine"):
        default_query_router.resolve_engine("milvus")


@pytest.mark.asyncio
async def test_graph_stub_returns_warning_not_crash():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        stub = GraphRetrievalEngineStub()
        result = await stub.retrieve_with_availability(
            session=session,
            query="who reports to whom?",
            requester_identity="alice@example.com",
            top_k=5,
        )
        assert result.evidence == []
        assert any("graph_engine_not_enabled" in w for w in result.source_availability_warning)

        router = QueryRouter(
            engines={
                RetrievalEngineKind.VECTOR: VectorHybridEngine(),
                RetrievalEngineKind.GRAPH: stub,
            }
        )
        routed = await router.retrieve(
            session=session,
            query="who reports to whom?",
            requester_identity="alice@example.com",
            engine="graph",
        )
        assert routed.evidence == []
    await engine.dispose()
