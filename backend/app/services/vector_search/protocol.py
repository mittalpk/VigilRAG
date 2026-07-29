"""Vector search backend abstraction for replaceable ANN indexes (US-038 / FEAT-20)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class ChunkResult:
    """Ranked chunk hit returned by a VectorSearchBackend."""

    chunk_id: str
    score: float
    source_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)


class VectorSearchBackend(Protocol):
    """
    Pluggable vector index interface (NFR-010).

    Swapping pgvector → Qdrant/Weaviate is a configuration change via
    ``VECTOR_SEARCH_BACKEND``, not an application rewrite.
    """

    async def search(
        self,
        query_embedding: List[float],
        top_k: int,
        source_ids: Optional[List[str]] = None,
    ) -> List[ChunkResult]:
        """Return top-k nearest neighbors, optionally filtered by source_ids."""
        ...

    async def upsert(
        self,
        chunk_id: str,
        embedding: List[float],
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert or update a chunk embedding + metadata payload."""
        ...

    async def delete(self, chunk_id: str) -> None:
        """Remove a chunk from the vector index."""
        ...

    async def count(self) -> int:
        """Return number of indexed vectors (for migration validation)."""
        ...

    @property
    def backend_name(self) -> str:
        ...
