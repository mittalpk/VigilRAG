"""
VigilRAG Unified Knowledge API Router (US-008 / US-028 / US-036).

Provides:
- POST /api/v1/knowledge/query endpoint powered by HybridRetrievalEngine over database chunks,
  instrumented with OpenTelemetry distributed tracing and graceful connector degradation.
"""

import datetime
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header
from fastapi.responses import JSONResponse

from backend.app.auth import get_current_user, require_role
from backend.app.models import AsyncSessionLocal
from backend.app.schemas import HybridRetrievalResponse, KnowledgeQueryRequest
from backend.app.services.hybrid_retrieval_engine import HybridRetrievalEngine
from backend.app.tracing import trace_span

router = APIRouter()
logger = logging.getLogger(__name__)

retrieval_engine = HybridRetrievalEngine()


# GAP-F03: viewer role cannot submit new queries (US-016 RBAC requirement)
_require_query_role = require_role(["admin", "user"])


@router.post("/query", response_model=HybridRetrievalResponse)
async def query_knowledge(
    body: KnowledgeQueryRequest = Body(...),
    current_user: dict = Depends(get_current_user),
    _role_check: None = Depends(_require_query_role),
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

    source_warnings: list = []
    with trace_span("knowledge_api.retrieve", attributes=span_attributes, trace_id=trace_id):
        # Execute Hybrid Search over SQLAlchemy database chunks
        async with AsyncSessionLocal() as session:
            retrieval_result = await retrieval_engine.retrieve_with_availability(
                session=session,
                query=body.query,
                requester_identity=requester_identity,
                top_k=body.top_k,
            )
            evidence = retrieval_result.evidence
            source_warnings = list(retrieval_result.source_availability_warning or [])

            # US-030: Analyze evidence freshness and conflicts
            from backend.app.services.freshness_service import FreshnessConflictEvaluator
            freshness_evaluator = FreshnessConflictEvaluator()
            analysis_res = freshness_evaluator.analyze(evidence)

            # Update evidence items with freshness signals
            for ev in evidence:
                sig = analysis_res.freshness_signals.get(ev.chunk_id)
                if sig:
                    ev.is_stale = sig.is_stale
                    ev.last_modified_date = sig.last_modified_date
                    ev.staleness_warning = sig.staleness_warning

            # GAP-F01: Assign query_id before the try block so it is always available for the response.
            # This ensures the frontend can use query_id (not trace_id) for feedback submission.
            query_id = f"qry-{uuid.uuid4().hex[:12]}"

            # Persist Query and Evidence audit records for provenance tracking (US-013)
            try:
                ev_dicts = [ev.model_dump() for ev in evidence]
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

    conflicts_schema = [
        {
            "has_conflict": c.has_conflict,
            "conflict_type": c.conflict_type or "unknown",
            "description": c.description or "",
            "conflicting_chunk_ids": c.conflicting_chunk_ids,
        }
        for c in analysis_res.conflicts
    ]

    response = HybridRetrievalResponse(
        evidence=evidence,
        trace_id=trace_id,
        query_id=query_id,  # GAP-F01: expose query_id for feedback capture (US-019)
        execution_time_ms=exec_time_ms,
        query=body.query,
        total_retrieved=len(evidence),
        stale_count=analysis_res.overall_stale_count,
        conflicts=conflicts_schema,
        source_availability_warning=source_warnings,
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
                elif source_warnings:
                    headers["X-VigilRAG-Warning"] = "sources-unavailable"
                else:
                    headers["X-VigilRAG-Info"] = "all-results-filtered-by-permission"
        except Exception:
            headers["X-VigilRAG-Warning"] = "corpus-empty"

    return JSONResponse(content=response.model_dump(), headers=headers)
