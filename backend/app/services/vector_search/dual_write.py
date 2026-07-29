"""Dual-write vector search wrapper for safe migration cutover (US-038)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.app.services.vector_search.protocol import ChunkResult, VectorSearchBackend

logger = logging.getLogger(__name__)


class DualWriteVectorSearchBackend:
    """
    Reads from ``primary`` (typically pgvector); writes to primary + secondary.

    Used when ``VECTOR_SEARCH_DUAL_WRITE=true`` during migration validation.
    """

    def __init__(self, primary: VectorSearchBackend, secondary: VectorSearchBackend):
        self.primary = primary
        self.secondary = secondary

    @property
    def backend_name(self) -> str:
        return f"dual:{self.primary.backend_name}+{self.secondary.backend_name}"

    async def search(
        self,
        query_embedding: List[float],
        top_k: int,
        source_ids: Optional[List[str]] = None,
    ) -> List[ChunkResult]:
        return await self.primary.search(query_embedding, top_k, source_ids)

    async def upsert(
        self,
        chunk_id: str,
        embedding: List[float],
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self.primary.upsert(chunk_id, embedding, payload)
        try:
            await self.secondary.upsert(chunk_id, embedding, payload)
        except Exception as exc:
            logger.error(f"Dual-write secondary upsert failed for {chunk_id}: {exc}")
            raise

    async def delete(self, chunk_id: str) -> None:
        await self.primary.delete(chunk_id)
        try:
            await self.secondary.delete(chunk_id)
        except Exception as exc:
            logger.warning(f"Dual-write secondary delete failed for {chunk_id}: {exc}")

    async def count(self) -> int:
        return await self.primary.count()

    async def compare_search_consistency(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        source_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Compare primary vs secondary top-k id sets for cutover readiness."""
        primary_hits = await self.primary.search(query_embedding, top_k, source_ids)
        secondary_hits = await self.secondary.search(query_embedding, top_k, source_ids)
        p_ids = {h.chunk_id for h in primary_hits}
        s_ids = {h.chunk_id for h in secondary_hits}
        overlap = p_ids & s_ids
        union = p_ids | s_ids
        jaccard = (len(overlap) / len(union)) if union else 1.0
        return {
            "primary_ids": sorted(p_ids),
            "secondary_ids": sorted(s_ids),
            "overlap_count": len(overlap),
            "jaccard": round(jaccard, 4),
            "consistent": jaccard >= 0.8,
        }
