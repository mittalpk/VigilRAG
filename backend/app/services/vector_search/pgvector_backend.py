"""
Pgvector / Postgres-backed vector search (US-038).

MVP store keeps embeddings as JSON in ``Chunk.embedding_vector_str`` and ranks
via cosine similarity (same behaviour as the pre-abstraction hybrid engine).
When a true pgvector ``vector`` column is available, this backend can be
extended to use ``ORDER BY embedding <=> :q`` without changing callers.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Chunk
from backend.app.services.vector_search.protocol import ChunkResult

logger = logging.getLogger(__name__)


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


class PgvectorBackend:
    """Default VECTOR_SEARCH_BACKEND=pgvector implementation."""

    def __init__(self, session: AsyncSession):
        self._session = session

    @property
    def backend_name(self) -> str:
        return "pgvector"

    async def search(
        self,
        query_embedding: List[float],
        top_k: int,
        source_ids: Optional[List[str]] = None,
    ) -> List[ChunkResult]:
        stmt = select(Chunk).where(Chunk.deleted_at.is_(None))
        if source_ids:
            stmt = stmt.where(Chunk.source_id.in_(source_ids))
        # Bound candidate set for MVP in-process cosine (pilot ≤50K)
        stmt = stmt.limit(max(top_k * 20, 100))
        res = await self._session.execute(stmt)
        chunks = list(res.scalars().all())

        scored: List[ChunkResult] = []
        for chk in chunks:
            score = 0.0
            if chk.embedding_vector_str:
                try:
                    vec = json.loads(chk.embedding_vector_str)
                    score = cosine_similarity(query_embedding, vec)
                except Exception:
                    score = 0.0
            scored.append(
                ChunkResult(
                    chunk_id=chk.id,
                    score=score,
                    source_id=chk.source_id,
                    payload={"content_len": len(chk.content or "")},
                )
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    async def upsert(
        self,
        chunk_id: str,
        embedding: List[float],
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist embedding onto the Chunk row (source of truth remains Postgres)."""
        stmt = select(Chunk).where(Chunk.id == chunk_id)
        res = await self._session.execute(stmt)
        chunk = res.scalar_one_or_none()
        if chunk is None:
            logger.warning(f"PgvectorBackend.upsert: chunk '{chunk_id}' not found")
            return
        chunk.embedding_vector_str = json.dumps(embedding)
        if payload and payload.get("source_id"):
            chunk.source_id = payload["source_id"]
        await self._session.flush()

    async def delete(self, chunk_id: str) -> None:
        stmt = select(Chunk).where(Chunk.id == chunk_id)
        res = await self._session.execute(stmt)
        chunk = res.scalar_one_or_none()
        if chunk is None:
            return
        chunk.embedding_vector_str = None
        await self._session.flush()

    async def count(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.deleted_at.is_(None), Chunk.embedding_vector_str.is_not(None))
        )
        res = await self._session.execute(stmt)
        return int(res.scalar() or 0)

    async def rank_candidates(
        self,
        query_embedding: List[float],
        chunks: List[Chunk],
    ) -> List[str]:
        """Rank an already-fetched candidate set (used by HybridRetrievalEngine)."""
        scored: List[tuple[str, float]] = []
        for chk in chunks:
            score = 0.0
            if chk.embedding_vector_str:
                try:
                    vec = json.loads(chk.embedding_vector_str)
                    score = cosine_similarity(query_embedding, vec)
                except Exception:
                    score = 0.0
            scored.append((chk.id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [cid for cid, _ in scored]
