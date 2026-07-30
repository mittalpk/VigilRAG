"""
Modular query router / retrieval planner (demo-readiness / FR-001 extension).

Routes knowledge queries to pluggable retrieval engines. The production engine
is hybrid vector+keyword search; a graph engine stub is registered for future
GraphRAG cutover without changing the Knowledge API contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.schemas import EvidenceItem
from backend.app.services.hybrid_retrieval_engine import HybridRetrievalEngine, HybridRetrievalResult


class RetrievalEngineKind(str, Enum):
    VECTOR = "vector"
    GRAPH = "graph"
    AUTO = "auto"


class RetrievalEngine(Protocol):
    """Pluggable retrieval backend behind the Knowledge API query planner."""

    kind: RetrievalEngineKind

    async def retrieve_with_availability(
        self,
        session: AsyncSession,
        query: str,
        requester_identity: str,
        top_k: int = 5,
    ) -> HybridRetrievalResult:
        ...


@dataclass
class VectorHybridEngine:
    """Adapter: existing HybridRetrievalEngine as a RetrievalEngine."""

    kind: RetrievalEngineKind = field(default=RetrievalEngineKind.VECTOR, init=False)
    _inner: HybridRetrievalEngine = field(default_factory=HybridRetrievalEngine)

    async def retrieve_with_availability(
        self,
        session: AsyncSession,
        query: str,
        requester_identity: str,
        top_k: int = 5,
    ) -> HybridRetrievalResult:
        return await self._inner.retrieve_with_availability(
            session=session,
            query=query,
            requester_identity=requester_identity,
            top_k=top_k,
        )


@dataclass
class GraphRetrievalEngineStub:
    """
    Future GraphRAG engine placeholder (Phase 4+ / FEAT-13).

    Returns empty evidence with an availability warning so AUTO routing can fall
    back to vector without breaking the API contract.
    """

    kind: RetrievalEngineKind = field(default=RetrievalEngineKind.GRAPH, init=False)

    async def retrieve_with_availability(
        self,
        session: AsyncSession,
        query: str,
        requester_identity: str,
        top_k: int = 5,
    ) -> HybridRetrievalResult:
        return HybridRetrievalResult(
            evidence=[],
            source_availability_warning=[
                "graph_engine_not_enabled: GraphRAG retrieval is deferred to Phase 4+; use engine=vector or auto."
            ],
        )


class QueryRouter:
    """
    Broker / query planner: select retrieval engine(s) for a knowledge query.

    ``AUTO`` uses the vector hybrid engine today and reserves graph for when
    relationship-shaped queries are validated (DATA_ARCHITECTURE §5.1).
    """

    def __init__(
        self,
        engines: Optional[dict[RetrievalEngineKind, RetrievalEngine]] = None,
        default: RetrievalEngineKind = RetrievalEngineKind.AUTO,
    ):
        self._engines: dict[RetrievalEngineKind, RetrievalEngine] = engines or {
            RetrievalEngineKind.VECTOR: VectorHybridEngine(),
            RetrievalEngineKind.GRAPH: GraphRetrievalEngineStub(),
        }
        self._default = default

    def resolve_engine(self, preferred: Optional[str] = None) -> RetrievalEngineKind:
        if preferred:
            try:
                kind = RetrievalEngineKind(preferred.strip().lower())
            except ValueError as exc:
                raise ValueError(
                    f"Unknown retrieval engine '{preferred}'. "
                    f"Supported: {[e.value for e in RetrievalEngineKind]}"
                ) from exc
            if kind == RetrievalEngineKind.AUTO:
                return RetrievalEngineKind.VECTOR
            return kind
        if self._default == RetrievalEngineKind.AUTO:
            return RetrievalEngineKind.VECTOR
        return self._default

    async def retrieve(
        self,
        session: AsyncSession,
        query: str,
        requester_identity: str,
        top_k: int = 5,
        engine: Optional[str] = None,
    ) -> HybridRetrievalResult:
        kind = self.resolve_engine(engine)
        backend = self._engines.get(kind)
        if backend is None:
            raise ValueError(f"No retrieval engine registered for '{kind.value}'")
        result = await backend.retrieve_with_availability(
            session=session,
            query=query,
            requester_identity=requester_identity,
            top_k=top_k,
        )
        # AUTO/graph stub: if graph was forced and empty, surface warning only
        if kind == RetrievalEngineKind.GRAPH and not result.evidence:
            return result
        return result


# Process-wide default router used by the Knowledge API
default_query_router = QueryRouter()
