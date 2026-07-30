"""
VigilRAG Unified Knowledge API Router (US-008 / US-028 / US-036).

Provides:
- POST /api/v1/knowledge/query endpoint via modular QueryRouter (vector hybrid today; graph stub for future),
  instrumented with OpenTelemetry distributed tracing and graceful connector degradation.
"""

import datetime
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse

from backend.app.auth import get_current_user, require_role
from backend.app.models import AsyncSessionLocal
from backend.app.schemas import HybridRetrievalResponse, KnowledgeQueryRequest
from backend.app.services.query_router import (
    RetrievalEngineKind,
    VectorHybridEngine,
    default_query_router,
)
from backend.app.tracing import trace_span

router = APIRouter()
logger = logging.getLogger(__name__)

_require_query_role = require_role(["admin", "user"])

# Backward-compatible alias for tests that configure/patch the hybrid engine directly
_vector_adapter = default_query_router._engines[RetrievalEngineKind.VECTOR]
assert isinstance(_vector_adapter, VectorHybridEngine)
retrieval_engine = _vector_adapter._inner


@router.post("/query", response_model=HybridRetrievalResponse)
async def query_knowledge(
    body: KnowledgeQueryRequest = Body(...),
    current_user: dict = Depends(get_current_user),
    _role_check: None = Depends(_require_query_role),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    start_time = datetime.datetime.now()
    trace_id = x_trace_id or f"trc-{uuid.uuid4().hex[:12]}"
    requester_identity = current_user.get("sub", "user@example.com")

    span_attributes = {
        "query.length": len(body.query),
        "retrieval.top_k": body.top_k,
        "requester_identity": requester_identity,
        "retrieval.engine": body.engine or "auto",
    }

    source_warnings: list = []
    groundedness_score = None
    engine_used = "vector"

    with trace_span("knowledge_api.retrieve", attributes=span_attributes, trace_id=trace_id):
        async with AsyncSessionLocal() as session:
            try:
                engine_used = default_query_router.resolve_engine(body.engine).value
                retrieval_result = await default_query_router.retrieve(
                    session=session,
                    query=body.query,
                    requester_identity=requester_identity,
                    top_k=body.top_k,
                    engine=body.engine,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc

            evidence = retrieval_result.evidence
            source_warnings = list(retrieval_result.source_availability_warning or [])

            from backend.app.services.freshness_service import FreshnessConflictEvaluator

            freshness_evaluator = FreshnessConflictEvaluator()
            analysis_res = freshness_evaluator.analyze(evidence)

            for ev in evidence:
                sig = analysis_res.freshness_signals.get(ev.chunk_id)
                if sig:
                    ev.is_stale = sig.is_stale
                    ev.last_modified_date = sig.last_modified_date
                    ev.staleness_warning = sig.staleness_warning

            query_id = f"qry-{uuid.uuid4().hex[:12]}"
            answer_text = f"Retrieved {len(evidence)} evidence items via {engine_used} engine."

            try:
                from backend.app.services.groundedness_service import (
                    calculate_groundedness_and_used_chunks,
                    persist_query_evidence_answer,
                )

                ev_dicts = [ev.model_dump() for ev in evidence]
                groundedness_score, updated_ev = calculate_groundedness_and_used_chunks(
                    ev_dicts, answer_text
                )
                await persist_query_evidence_answer(
                    session=session,
                    query_id=query_id,
                    requester_identity=requester_identity,
                    query_text=body.query,
                    trace_id=trace_id,
                    evidence_items=updated_ev,
                    answer_text=answer_text,
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
        query_id=query_id,
        execution_time_ms=exec_time_ms,
        query=body.query,
        total_retrieved=len(evidence),
        stale_count=analysis_res.overall_stale_count,
        conflicts=conflicts_schema,
        source_availability_warning=source_warnings,
        groundedness_score=groundedness_score,
        retrieval_engine=engine_used,
    )

    headers = {}
    if len(evidence) == 0:
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import func, select
                from backend.app.models import Chunk

                cnt_res = await session.execute(
                    select(func.count()).select_from(Chunk).where(Chunk.deleted_at.is_(None))
                )
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
