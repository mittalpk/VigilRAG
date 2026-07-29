"""
Compliance Audit Log Router for US-018 + US-039 (FEAT-08).

Provides:
- GET /api/v1/audit/queries — Paginated list with identity, date, and full-text (?q=) filters.
- GET /api/v1/audit/queries/{query_id} — Single Query audit detail with EvidenceItem[].
- POST /api/v1/audit/export — Admin-only CSV/PDF/JSON export with TTL download URL.
- GET /api/v1/audit/exports/{export_id}/download — Token-authenticated download (1h TTL).
- GET /api/v1/audit/retention — Retention policy + latest run status.
- POST /api/v1/audit/digest — Trigger a compliance digest (admin / ops).
"""

from datetime import datetime
import json
import logging
from typing import List, Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.auth import require_admin
from backend.app.models import AnswerRecord, Chunk, EvidenceItemRecord, QueryRecord, get_db_session
from backend.app.schemas import (
    AuditDigestResponse,
    AuditEvidenceItem,
    AuditExportRequest,
    AuditExportResponse,
    AuditQueryDetailResponse,
    AuditQueryItem,
    AuditQueryListResponse,
    AuditRetentionStatusResponse,
)
from backend.app.services.audit_digest_service import send_audit_digest
from backend.app.services.audit_export_service import (
    create_audit_export,
    get_export_for_download,
    log_meta_audit,
)
from backend.app.services.audit_retention_service import get_retention_status

router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_optional_date(value: Optional[str]) -> Optional[datetime]:
    if not value or not value.strip():
        return None
    raw = value.strip()
    try:
        if len(raw) == 10:
            raw = f"{raw}T00:00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


@router.get("/queries", response_model=AuditQueryListResponse)
async def list_audit_queries(
    identity: Optional[str] = Query(None, description="Filter by requester identity (email or username)"),
    from_date: Optional[str] = Query(None, description="Filter queries from date (ISO format or YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Filter queries to date (ISO format or YYYY-MM-DD)"),
    q: Optional[str] = Query(None, description="Full-text search over query text (US-039)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Page size"),
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Admin-only endpoint returning paginated query audit records filtered by identity,
    date range, and optional full-text search term ``q``.
    """
    query_stmt = select(QueryRecord)
    count_stmt = select(func.count()).select_from(QueryRecord)

    filters = []
    if identity and identity.strip():
        filters.append(QueryRecord.requester_identity.ilike(f"%{identity.strip()}%"))

    from_dt = _parse_optional_date(from_date)
    if from_dt is not None:
        filters.append(QueryRecord.created_at >= from_dt)

    to_dt = _parse_optional_date(to_date)
    if to_dt is not None:
        filters.append(QueryRecord.created_at <= to_dt)

    if q and q.strip():
        # Portable FTS: ILIKE works on SQLite and Postgres; GIN FTS index accelerates Postgres.
        filters.append(QueryRecord.query_text.ilike(f"%{q.strip()}%"))

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
    for qr in query_records:
        ans_stmt = select(AnswerRecord).where(AnswerRecord.query_id == qr.id).limit(1)
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
                query_id=qr.id,
                requester_identity=qr.requester_identity,
                text=qr.query_text,
                timestamp=qr.created_at.isoformat() if qr.created_at else "",
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

    ev_stmt = (
        select(EvidenceItemRecord)
        .where(EvidenceItemRecord.query_id == query_id)
        .order_by(EvidenceItemRecord.created_at.asc())
        .limit(50)
    )
    ev_res = await session.execute(ev_stmt)
    ev_recs = ev_res.scalars().all()

    chunk_ids = [ev.chunk_id for ev in ev_recs]
    chunk_content_map: dict = {}
    if chunk_ids:
        try:
            ch_stmt = select(Chunk.id, Chunk.content).where(Chunk.id.in_(chunk_ids))
            ch_res = await session.execute(ch_stmt)
            for row in ch_res.fetchall():
                chunk_content_map[row[0]] = row[1]
        except Exception as exc:
            logger.warning(f"Could not load chunk content for audit detail: {exc}")

    evidence_items = [
        AuditEvidenceItem(
            id=ev.id,
            chunk_id=ev.chunk_id,
            content_excerpt=(chunk_content_map.get(ev.chunk_id, "") or "")[:500],
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


@router.post("/export", response_model=None)
async def export_audit_log(
    body: Optional[AuditExportRequest] = Body(None),
    from_date: Optional[str] = Query(None, alias="from", description="Range start (query-param form)"),
    to_date: Optional[str] = Query(None, alias="to", description="Range end (query-param form)"),
    format: Optional[str] = Query(None, description="csv|pdf|json"),
    identity: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> Union[AuditExportResponse, JSONResponse]:
    """
    Admin-only compliance export. Accepts JSON body and/or ``from``/``to``/``format`` query params.
    Large ranges return HTTP 202 with async semantics; download URLs expire after 1 hour.
    """
    from_val = (body.from_date if body else None) or from_date
    to_val = (body.to_date if body else None) or to_date
    fmt = (body.format if body else None) or format or "csv"
    identity_val = (body.identity if body else None) or identity
    q_val = (body.q if body else None) or q
    force_async = bool(body.force_async) if body else False

    if not from_val or not to_val:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from and to date parameters are required",
        )

    try:
        result = await create_audit_export(
            session,
            requested_by=admin_identity,
            from_date=from_val,
            to_date=to_val,
            fmt=fmt,
            identity=identity_val,
            q=q_val,
            force_async=force_async,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    payload = {
        "export_id": result["export_id"],
        "status": result["status"],
        "async": bool(result.get("async")),
        "row_count": int(result.get("row_count") or 0),
        "download_url": result.get("download_url"),
        "expires_at": result.get("expires_at"),
        "message": result.get("message"),
    }

    if result.get("async"):
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload)
    return AuditExportResponse.model_validate(payload)


@router.get("/exports/{export_id}/download")
async def download_audit_export(
    export_id: str,
    token: str = Query(..., description="One-time TTL download token"),
    session: AsyncSession = Depends(get_db_session),
):
    """Token-authenticated download; rejects expired or invalid tokens (NFR-002)."""
    try:
        export, data, media_type = await get_export_for_download(session, export_id, token)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await log_meta_audit(
        session,
        actor=export.requested_by,
        action="export_downloaded",
        detail=f"export_id={export_id};format={export.format};bytes={len(data)}",
    )

    filename = f"vigilrag-audit-{export_id}.{export.format}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/retention", response_model=AuditRetentionStatusResponse)
async def audit_retention_status(
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin-only retention policy and recent retention run status."""
    data = await get_retention_status(session)
    return AuditRetentionStatusResponse(**data)


@router.post("/digest", response_model=AuditDigestResponse)
async def trigger_audit_digest(
    cadence: str = Query("weekly", description="weekly|monthly"),
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin-only trigger for the compliance digest job (also runnable via scripts/send_audit_digest.py)."""
    try:
        result = await send_audit_digest(session, cadence=cadence)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    await log_meta_audit(
        session,
        actor=admin_identity,
        action="digest_sent",
        detail=f"cadence={cadence};status={result.get('status')}",
    )
    return AuditDigestResponse(
        status=result["status"],
        stats=result["stats"],
        delivery=result["delivery"],
        scheduled_report_id=result.get("scheduled_report_id"),
        markdown=result.get("markdown"),
    )
