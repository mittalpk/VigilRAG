"""
Qdrant-backed vector search via REST API (US-038).

Configured with ``VECTOR_SEARCH_BACKEND=qdrant`` and ``QDRANT_URL``.
Uses httpx (already a project dependency) — no mandatory qdrant-client package.
Includes an in-memory fallback used when Qdrant is unreachable (tests / local).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from backend.app.services.vector_search.pgvector_backend import cosine_similarity
from backend.app.services.vector_search.protocol import ChunkResult

logger = logging.getLogger(__name__)


class QdrantVectorSearchBackend:
    """VECTOR_SEARCH_BACKEND=qdrant implementation (preferred self-hosted target)."""

    def __init__(
        self,
        url: str,
        collection: str = "vigilrag_chunks",
        api_key: Optional[str] = None,
        timeout: float = 10.0,
        vector_size: int = 768,
        allow_memory_fallback: bool = True,
    ):
        self.url = (url or "").rstrip("/")
        self.collection = collection
        self.api_key = api_key or ""
        self.timeout = timeout
        self.vector_size = vector_size
        self.allow_memory_fallback = allow_memory_fallback
        self._memory: Dict[str, Dict[str, Any]] = {}
        self._using_memory = False

    @property
    def backend_name(self) -> str:
        return "qdrant-memory" if self._using_memory else "qdrant"

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        return headers

    async def _ensure_collection(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(
            f"{self.url}/collections/{self.collection}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        if resp.status_code == 200:
            return
        # Create collection
        payload = {
            "vectors": {
                "size": self.vector_size,
                "distance": "Cosine",
            }
        }
        create = await client.put(
            f"{self.url}/collections/{self.collection}",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        if create.status_code not in (200, 201):
            raise RuntimeError(f"Failed to create Qdrant collection: {create.status_code} {create.text}")

    async def search(
        self,
        query_embedding: List[float],
        top_k: int,
        source_ids: Optional[List[str]] = None,
    ) -> List[ChunkResult]:
        if self._using_memory or not self.url:
            return self._memory_search(query_embedding, top_k, source_ids)

        try:
            async with httpx.AsyncClient() as client:
                await self._ensure_collection(client)
                body: Dict[str, Any] = {
                    "vector": query_embedding,
                    "limit": top_k,
                    "with_payload": True,
                }
                if source_ids:
                    body["filter"] = {
                        "must": [{"key": "source_id", "match": {"any": source_ids}}]
                    }
                resp = await client.post(
                    f"{self.url}/collections/{self.collection}/points/search",
                    headers=self._headers(),
                    json=body,
                    timeout=self.timeout,
                )
                if resp.status_code >= 400:
                    raise RuntimeError(f"Qdrant search failed: {resp.status_code}")
                results = []
                for hit in resp.json().get("result") or []:
                    payload = hit.get("payload") or {}
                    results.append(
                        ChunkResult(
                            chunk_id=str(hit.get("id") or payload.get("chunk_id") or ""),
                            score=float(hit.get("score") or 0.0),
                            source_id=payload.get("source_id"),
                            payload=payload,
                        )
                    )
                return results
        except Exception as exc:
            logger.warning(f"Qdrant search unavailable ({exc}); using memory fallback")
            if not self.allow_memory_fallback:
                raise
            self._using_memory = True
            return self._memory_search(query_embedding, top_k, source_ids)

    def _memory_search(
        self,
        query_embedding: List[float],
        top_k: int,
        source_ids: Optional[List[str]],
    ) -> List[ChunkResult]:
        scored: List[ChunkResult] = []
        for cid, entry in self._memory.items():
            if source_ids and entry.get("source_id") not in source_ids:
                continue
            score = cosine_similarity(query_embedding, entry.get("embedding") or [])
            scored.append(
                ChunkResult(
                    chunk_id=cid,
                    score=score,
                    source_id=entry.get("source_id"),
                    payload=entry.get("payload") or {},
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
        payload = dict(payload or {})
        payload.setdefault("chunk_id", chunk_id)
        self._memory[chunk_id] = {
            "embedding": list(embedding),
            "source_id": payload.get("source_id"),
            "payload": payload,
        }

        if self._using_memory or not self.url:
            self._using_memory = True
            return

        try:
            async with httpx.AsyncClient() as client:
                await self._ensure_collection(client)
                body = {
                    "points": [
                        {
                            "id": chunk_id if chunk_id.replace("-", "").isalnum() else abs(hash(chunk_id)) % (10**12),
                            "vector": embedding,
                            "payload": payload,
                        }
                    ]
                }
                # Prefer string UUID-like ids when possible; Qdrant accepts uint or UUID
                # For non-UUID chunk ids use hash int and store chunk_id in payload
                if not _looks_like_uuid(chunk_id):
                    body["points"][0]["id"] = abs(hash(chunk_id)) % (10**12)
                resp = await client.put(
                    f"{self.url}/collections/{self.collection}/points?wait=true",
                    headers=self._headers(),
                    json=body,
                    timeout=self.timeout,
                )
                if resp.status_code >= 400:
                    raise RuntimeError(f"Qdrant upsert failed: {resp.status_code} {resp.text}")
        except Exception as exc:
            logger.warning(f"Qdrant upsert unavailable ({exc}); memory fallback active")
            if not self.allow_memory_fallback:
                raise
            self._using_memory = True

    async def delete(self, chunk_id: str) -> None:
        self._memory.pop(chunk_id, None)
        if self._using_memory or not self.url:
            return
        try:
            point_id = chunk_id if _looks_like_uuid(chunk_id) else abs(hash(chunk_id)) % (10**12)
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.url}/collections/{self.collection}/points/delete?wait=true",
                    headers=self._headers(),
                    json={"points": [point_id]},
                    timeout=self.timeout,
                )
        except Exception as exc:
            logger.warning(f"Qdrant delete failed ({exc})")

    async def count(self) -> int:
        if self._using_memory or not self.url:
            return len(self._memory)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.url}/collections/{self.collection}",
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                if resp.status_code >= 400:
                    return len(self._memory)
                return int(resp.json().get("result", {}).get("points_count") or 0)
        except Exception:
            return len(self._memory)


def _looks_like_uuid(value: str) -> bool:
    parts = value.split("-")
    return len(parts) == 5 and all(p.isalnum() for p in parts)
