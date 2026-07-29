"""
VigilRAG Unified Knowledge API Router (US-008 / US-028).

Provides:
- POST /api/v1/knowledge/query endpoint powered by HybridRetrievalEngine over database chunks,
  instrumented with OpenTelemetry distributed tracing.
"""

import datetime
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header
from fastapi.responses import JSONResponse

from backend.app.auth import get_current_user
from backend.app.models import AsyncSessionLocal
from backend.app.schemas import HybridRetrievalResponse, KnowledgeQueryRequest
from backend.app.services.hybrid_retrieval_engine import HybridRetrievalEngine
from backend.app.tracing import trace_span

router = APIRouter()
logger = logging.getLogger(__name__)

retrieval_engine = HybridRetrievalEngine()


@router.post("/query", response_model=HybridRetrievalResponse)
async def query_knowledge(
    body: KnowledgeQueryRequest = Body(...),
    current_user: dict = Depends(get_current_user),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    start_time = datetime.datetime.now()
    trace_id = x_trace_id or f"trc-{uuid.uuid4().hex[:12]}"

    # Extract validated requester identity from authenticated user payload
    requester_identity = current_user.get("sub", "user@example.com")

    span_attributes = {
        "query.length": len(body.query),
        "retrieval.top_k": body.top_k,
        "requester_identity": requester_identity,
    }

    with trace_span("knowledge_api.retrieve", attributes=span_attributes, trace_id=trace_id):
        # Execute Hybrid Search over SQLAlchemy database chunks
        async with AsyncSessionLocal() as session:
            evidence = await retrieval_engine.retrieve(
                session=session,
                query=body.query,
                requester_identity=requester_identity,
                top_k=body.top_k,
            )

            # Persist Query and Evidence audit records for provenance tracking (US-013)
            try:
                ev_dicts = [ev.model_dump() for ev in evidence]
                query_id = f"qry-{uuid.uuid4().hex[:12]}"
                from backend.app.services.groundedness_service import persist_query_evidence_answer
                await persist_query_evidence_answer(
                    session=session,
                    query_id=query_id,
                    requester_identity=requester_identity,
                    query_text=body.query,
                    trace_id=trace_id,
                    evidence_items=ev_dicts,
                    answer_text=f"Retrieved {len(evidence)} evidence items.",
                )
            except Exception as exc:
                logger.warning(f"Audit persistence warning: {exc}")

    exec_time_ms = int((datetime.datetime.now() - start_time).total_seconds() * 1000)

    response = HybridRetrievalResponse(
        evidence=evidence,
        trace_id=trace_id,
        execution_time_ms=exec_time_ms,
        query=body.query,
        total_retrieved=len(evidence),
    )

    headers = {}
    if len(evidence) == 0:
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import func, select
                from backend.app.models import Chunk
                cnt_res = await session.execute(select(func.count()).select_from(Chunk).where(Chunk.deleted_at.is_(None)))
                total_chunks = cnt_res.scalar() or 0
                if total_chunks == 0:
                    headers["X-VigilRAG-Warning"] = "corpus-empty"
                else:
                    headers["X-VigilRAG-Info"] = "all-results-filtered-by-permission"
        except Exception:
            headers["X-VigilRAG-Warning"] = "corpus-empty"

    return JSONResponse(content=response.model_dump(), headers=headers)
