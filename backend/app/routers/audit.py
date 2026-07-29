"""
Compliance Audit Log Router for US-018 (FEAT-08).

Provides:
- GET /api/v1/audit/queries — Paginated list of Query audit records with identity and date range filtering.
- GET /api/v1/audit/queries/{query_id} — Single Query audit detail record with EvidenceItem[] list.
"""

from datetime import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.auth import require_admin
from backend.app.models import AnswerRecord, EvidenceItemRecord, QueryRecord, get_db_session
from backend.app.schemas import (
    AuditEvidenceItem,
    AuditQueryDetailResponse,
    AuditQueryItem,
    AuditQueryListResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/queries", response_model=AuditQueryListResponse)
async def list_audit_queries(
    identity: Optional[str] = Query(None, description="Filter by requester identity (email or username)"),
    from_date: Optional[str] = Query(None, description="Filter queries from date (ISO format or YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Filter queries to date (ISO format or YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Page size"),
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Admin-only endpoint returning paginated query audit records filtered by identity and date range.
    """
    query_stmt = select(QueryRecord)
    count_stmt = select(func.count()).select_from(QueryRecord)

    filters = []
    if identity and identity.strip():
        filters.append(QueryRecord.requester_identity.ilike(f"%{identity.strip()}%"))

    if from_date and from_date.strip():
        try:
            from_dt = datetime.fromisoformat(from_date.strip())
            filters.append(QueryRecord.created_at >= from_dt)
        except ValueError:
            pass

    if to_date and to_date.strip():
        try:
            to_dt = datetime.fromisoformat(to_date.strip())
            filters.append(QueryRecord.created_at <= to_dt)
        except ValueError:
            pass

    if filters:
        query_stmt = query_stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    query_stmt = query_stmt.order_by(QueryRecord.created_at.desc())

    offset = (page - 1) * per_page
    query_stmt = query_stmt.offset(offset).limit(per_page)

    total_res = await session.execute(count_stmt)
    total = total_res.scalar() or 0

    items_res = await session.execute(query_stmt)
    query_records = items_res.scalars().all()

    items: List[AuditQueryItem] = []
    for q in query_records:
        ans_stmt = select(AnswerRecord).where(AnswerRecord.query_id == q.id).limit(1)
        ans_res = await session.execute(ans_stmt)
        ans_rec = ans_res.scalar_one_or_none()

        answer_text = ans_rec.answer_text if ans_rec else None
        groundedness_score = ans_rec.groundedness_score if ans_rec else None
        guardrail_flags = []
        if ans_rec and ans_rec.guardrail_flags_json:
            try:
                guardrail_flags = json.loads(ans_rec.guardrail_flags_json)
            except Exception:
                guardrail_flags = []

        items.append(
            AuditQueryItem(
                query_id=q.id,
                requester_identity=q.requester_identity,
                text=q.query_text,
                timestamp=q.created_at.isoformat() if q.created_at else "",
                answer_text=answer_text,
                citations=[],
                groundedness_score=groundedness_score,
                guardrail_flags=guardrail_flags,
            )
        )

    return AuditQueryListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/queries/{query_id}", response_model=AuditQueryDetailResponse)
async def get_audit_query_detail(
    query_id: str,
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Admin-only endpoint returning full detail for a single query, including associated evidence items.
    Caps returned evidence items at 50 with a `truncated: true` flag if more exist.
    """
    q_stmt = select(QueryRecord).where(QueryRecord.id == query_id)
    q_res = await session.execute(q_stmt)
    q_rec = q_res.scalar_one_or_none()

    if not q_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit query record '{query_id}' not found",
        )

    ans_stmt = select(AnswerRecord).where(AnswerRecord.query_id == query_id).limit(1)
    ans_res = await session.execute(ans_stmt)
    ans_rec = ans_res.scalar_one_or_none()

    answer_text = ans_rec.answer_text if ans_rec else None
    groundedness_score = ans_rec.groundedness_score if ans_rec else None
    guardrail_flags = []
    if ans_rec and ans_rec.guardrail_flags_json:
        try:
            guardrail_flags = json.loads(ans_rec.guardrail_flags_json)
        except Exception:
            guardrail_flags = []

    ev_count_stmt = select(func.count()).select_from(EvidenceItemRecord).where(EvidenceItemRecord.query_id == query_id)
    ev_count_res = await session.execute(ev_count_stmt)
    total_evidence = ev_count_res.scalar() or 0

    ev_stmt = select(EvidenceItemRecord).where(EvidenceItemRecord.query_id == query_id).order_by(EvidenceItemRecord.created_at.asc()).limit(50)
    ev_res = await session.execute(ev_stmt)
    ev_recs = ev_res.scalars().all()

    evidence_items = [
        AuditEvidenceItem(
            id=ev.id,
            chunk_id=ev.chunk_id,
            content_excerpt=f"Content excerpt for chunk {ev.chunk_id}",
            source_url=ev.source_url,
            relevance_score=ev.relevance_score,
            used_in_answer=ev.used_in_answer,
            permission_denied=False,
        )
        for ev in ev_recs
    ]

    truncated = total_evidence > 50

    return AuditQueryDetailResponse(
        query_id=q_rec.id,
        requester_identity=q_rec.requester_identity,
        text=q_rec.query_text,
        timestamp=q_rec.created_at.isoformat() if q_rec.created_at else "",
        answer_text=answer_text,
        citations=[],
        groundedness_score=groundedness_score,
        guardrail_flags=guardrail_flags,
        evidence_items=evidence_items,
        truncated=truncated,
    )
