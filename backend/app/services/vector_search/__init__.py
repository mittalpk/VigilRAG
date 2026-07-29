"""Factory for VectorSearchBackend selection via env config (US-038)."""

from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services.vector_search.dual_write import DualWriteVectorSearchBackend
from backend.app.services.vector_search.pgvector_backend import PgvectorBackend
from backend.app.services.vector_search.qdrant_backend import QdrantVectorSearchBackend

logger = logging.getLogger(__name__)


def get_vector_search_backend(
    session: AsyncSession,
    backend_name: Optional[str] = None,
    dual_write: Optional[bool] = None,
):
    """
    Resolve the configured vector search backend.

    Env:
      VECTOR_SEARCH_BACKEND=pgvector|qdrant  (default: pgvector)
      VECTOR_SEARCH_DUAL_WRITE=true|false
      QDRANT_URL, QDRANT_API_KEY, QDRANT_COLLECTION
    """
    name = (backend_name or os.getenv("VECTOR_SEARCH_BACKEND", "pgvector")).strip().lower()
    dual = dual_write if dual_write is not None else (
        os.getenv("VECTOR_SEARCH_DUAL_WRITE", "").strip().lower() in ("1", "true", "yes")
    )

    pg = PgvectorBackend(session)
    if name in ("pgvector", "postgres", "postgresql"):
        if dual:
            qdrant = _build_qdrant()
            logger.info("Vector search: dual-write pgvector (read) + qdrant (write)")
            return DualWriteVectorSearchBackend(primary=pg, secondary=qdrant)
        return pg

    if name == "qdrant":
        qdrant = _build_qdrant()
        if dual:
            logger.info("Vector search: dual-write qdrant (read) + pgvector (write)")
            return DualWriteVectorSearchBackend(primary=qdrant, secondary=pg)
        return qdrant

    logger.warning(f"Unknown VECTOR_SEARCH_BACKEND='{name}'; falling back to pgvector")
    return pg


def _build_qdrant() -> QdrantVectorSearchBackend:
    return QdrantVectorSearchBackend(
        url=os.getenv("QDRANT_URL", ""),
        collection=os.getenv("QDRANT_COLLECTION", "vigilrag_chunks"),
        api_key=os.getenv("QDRANT_API_KEY", "") or None,
        allow_memory_fallback=True,
    )
