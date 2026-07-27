"""
Admin Evaluation Runs Router for US-022.

Provides:
- GET /api/v1/admin/evaluation-runs — Paginated list of historical EvaluationRun records with filtering.
- GET /api/v1/admin/evaluation-runs/latest — Single most recent EvaluationRun record.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.auth import require_admin
from backend.app.models import EvaluationRun, get_db_session
from backend.app.schemas import EvaluationRunListResponse, EvaluationRunResponse

router = APIRouter()
logger = logging.getLogger(__name__)


def parse_run_model(run: EvaluationRun) -> EvaluationRunResponse:
    details = []
    if run.details_json:
        try:
            details = json.loads(run.details_json)
        except Exception:
            details = []

    return EvaluationRunResponse(
        id=run.id,
        pipeline_version=run.pipeline_version,
        dataset_version=run.dataset_version,
        total_cases=run.total_cases,
        faithfulness=run.faithfulness,
        context_precision=run.context_precision,
        context_recall=run.context_recall,
        answer_relevancy=run.answer_relevancy,
        passed_threshold=run.passed_threshold,
        run_at=run.run_at.isoformat() if run.run_at else "",
        details=details,
    )


@router.get("/evaluation-runs/latest", response_model=EvaluationRunResponse)
async def get_latest_evaluation_run(
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin-only endpoint returning the single most recent EvaluationRun record."""
    stmt = select(EvaluationRun).order_by(EvaluationRun.run_at.desc()).limit(1)
    res = await session.execute(stmt)
    latest = res.scalar_one_or_none()

    if not latest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No evaluation runs recorded. Run scripts/run_evaluation.py to generate the first record.",
        )

    return parse_run_model(latest)


@router.get("/evaluation-runs", response_model=EvaluationRunListResponse)
async def list_evaluation_runs(
    dataset_version: Optional[str] = Query(None, description="Filter by dataset version (e.g. v1.0)"),
    pipeline_version: Optional[str] = Query(None, description="Filter by pipeline version / git commit"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Page size"),
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin-only endpoint returning paginated EvaluationRun records."""
    query_stmt = select(EvaluationRun)
    count_stmt = select(func.count()).select_from(EvaluationRun)

    filters = []
    if dataset_version:
        filters.append(EvaluationRun.dataset_version == dataset_version)
    if pipeline_version:
        filters.append(EvaluationRun.pipeline_version == pipeline_version)

    if filters:
        query_stmt = query_stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    # Order by run_at descending
    query_stmt = query_stmt.order_by(EvaluationRun.run_at.desc())

    # Pagination
    offset = (page - 1) * size
    query_stmt = query_stmt.offset(offset).limit(size)

    total_res = await session.execute(count_stmt)
    total = total_res.scalar() or 0

    items_res = await session.execute(query_stmt)
    runs = items_res.scalars().all()

    items = [parse_run_model(run) for run in runs]

    return EvaluationRunListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
    )
