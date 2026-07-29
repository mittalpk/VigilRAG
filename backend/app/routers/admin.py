"""
Admin Evaluation Runs Router for US-022.

Provides:
- GET /api/v1/admin/evaluation-runs — Paginated list of historical EvaluationRun records with filtering.
- GET /api/v1/admin/evaluation-runs/latest — Single most recent EvaluationRun record.
"""

import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.auth import require_admin
from backend.app.models import AnswerRecord, EvaluationCase, EvaluationRun, FeedbackRecord, FeedbackReviewItem, QueryRecord, get_db_session
from backend.app.schemas import (
    CostDashboardResponse,
    CostDailyPoint,
    EvaluationRunListResponse,
    EvaluationRunResponse,
    FeedbackActionRequest,
    FeedbackReviewItemResponse,
    FeedbackReviewListResponse,
    HealthProbeRequest,
    HealthProbeResponse,
    QueryCostRecordRequest,
    QueryCostRecordResponse,
    SLOAlertEvaluateResponse,
    SLODailyPoint,
    SLODashboardResponse,
    AvailabilityAlertItem,
)

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


# ── Feedback Review Endpoints (US-020) ──────────────────────────────────────

@router.get("/feedback-review", response_model=FeedbackReviewListResponse)
async def list_feedback_review_items(
    status_filter: Optional[str] = Query(None, description="Filter by status (pending, promoted, dismissed, needs_investigation)"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Page size"),
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin-only endpoint returning paginated FeedbackReviewItem records with query & answer details."""
    query_stmt = select(FeedbackReviewItem)
    count_stmt = select(func.count()).select_from(FeedbackReviewItem)

    if status_filter and status_filter.strip():
        query_stmt = query_stmt.where(FeedbackReviewItem.status == status_filter.strip())
        count_stmt = count_stmt.where(FeedbackReviewItem.status == status_filter.strip())

    query_stmt = query_stmt.order_by(FeedbackReviewItem.created_at.desc())

    offset = (page - 1) * size
    query_stmt = query_stmt.offset(offset).limit(size)

    total_res = await session.execute(count_stmt)
    total = total_res.scalar() or 0

    items_res = await session.execute(query_stmt)
    review_items = items_res.scalars().all()

    items = []
    for item in review_items:
        # Load associated QueryRecord
        q_stmt = select(QueryRecord).where(QueryRecord.id == item.query_id)
        q_res = await session.execute(q_stmt)
        q_rec = q_res.scalar_one_or_none()

        # Load associated AnswerRecord
        ans_stmt = select(AnswerRecord).where(AnswerRecord.query_id == item.query_id).limit(1)
        ans_res = await session.execute(ans_stmt)
        ans_rec = ans_res.scalar_one_or_none()

        # Load associated FeedbackRecord if present
        fb_rec = None
        if item.feedback_id:
            fb_stmt = select(FeedbackRecord).where(FeedbackRecord.id == item.feedback_id)
            fb_res = await session.execute(fb_stmt)
            fb_rec = fb_res.scalar_one_or_none()

        items.append(
            FeedbackReviewItemResponse(
                id=item.id,
                feedback_id=item.feedback_id,
                query_id=item.query_id,
                requester_identity=q_rec.requester_identity if q_rec else "unknown",
                query_text=q_rec.query_text if q_rec else "",
                answer_text=ans_rec.answer_text if ans_rec else None,
                user_comment=fb_rec.comment if fb_rec else None,
                rating=fb_rec.rating if fb_rec else "negative",
                status=item.status,
                golden_answer=item.golden_answer,
                reviewed_by=item.reviewed_by,
                created_at=item.created_at.isoformat() if item.created_at else "",
            )
        )

    return FeedbackReviewListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
    )


@router.post("/feedback-review/{item_id}/action")
async def action_feedback_review_item(
    item_id: str,
    body: FeedbackActionRequest,
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Admin-only endpoint to promote, dismiss, or flag a FeedbackReviewItem.
    On promote: creates an EvaluationCase record in the golden dataset.
    """
    action_clean = body.action.strip().lower()
    if action_clean not in ("promote", "dismiss", "needs_investigation"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Action must be 'promote', 'dismiss', or 'needs_investigation'",
        )

    stmt = select(FeedbackReviewItem).where(FeedbackReviewItem.id == item_id)
    res = await session.execute(stmt)
    item = res.scalar_one_or_none()

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"FeedbackReviewItem '{item_id}' not found",
        )

    status_mapping = {
        "promote": "promoted",
        "dismiss": "dismissed",
        "needs_investigation": "needs_investigation",
    }
    item.status = status_mapping[action_clean]
    item.reviewed_by = admin_identity
    if body.golden_answer:
        item.golden_answer = body.golden_answer.strip()

    # If promoted, create EvaluationCase
    if action_clean == "promote":
        q_stmt = select(QueryRecord).where(QueryRecord.id == item.query_id)
        q_res = await session.execute(q_stmt)
        q_rec = q_res.scalar_one_or_none()

        query_text = q_rec.query_text if q_rec else "Promoted query case"
        golden_ans = body.golden_answer.strip() if body.golden_answer else ""

        eval_case = EvaluationCase(
            id=f"case-{uuid.uuid4().hex[:12]}",
            query=query_text,
            expected_answer=golden_ans,
            source_type="user_feedback",
            tags_json=json.dumps(["user_feedback", "promoted"]),
        )
        session.add(eval_case)

    await session.commit()
    return {"success": True, "item_id": item.id, "status": item.status}


# ── Cost Dashboard Endpoints (US-036 / NFR-009) ─────────────────────────────

@router.get("/costs/dashboard", response_model=CostDashboardResponse)
async def get_cost_dashboard(
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin-only cost-per-query dashboard (USD estimates from OTel token attributes)."""
    from backend.app.services.cost_service import get_cost_dashboard as build_cost_dashboard

    summary = await build_cost_dashboard(session, days=days)
    return CostDashboardResponse(
        total_cost_usd=summary.total_cost_usd,
        total_queries=summary.total_queries,
        avg_cost_per_query_usd=summary.avg_cost_per_query_usd,
        cost_by_model=summary.cost_by_model,
        daily_trend=[CostDailyPoint(**d) for d in summary.daily_trend],
        pi_total_cost_usd=summary.pi_total_cost_usd,
        alert_spike=summary.alert_spike,
        spike_message=summary.spike_message,
        window_days=days,
    )


@router.post("/costs/record", response_model=QueryCostRecordResponse, status_code=status.HTTP_201_CREATED)
async def record_cost(
    body: QueryCostRecordRequest,
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin/internal endpoint to persist a query cost row from OTel span attributes."""
    from backend.app.services.cost_service import normalize_model_family, record_query_cost

    if not body.query_id or not body.trace_id or not body.model:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="query_id, trace_id, and model are required",
        )

    record = await record_query_cost(
        session,
        query_id=body.query_id,
        trace_id=body.trace_id,
        model=body.model,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
    )
    await session.commit()
    return QueryCostRecordResponse(
        id=record.id,
        query_id=record.query_id,
        estimated_cost_usd=record.estimated_cost_usd,
        model_family=record.model_family or normalize_model_family(body.model),
    )


# ── SLO Dashboard Endpoints (US-036 / NFR-008) ──────────────────────────────

@router.get("/slo/dashboard", response_model=SLODashboardResponse)
async def get_slo_dashboard_endpoint(
    days: int = Query(30, ge=1, le=90, description="Rolling window in days"),
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin-only availability SLO dashboard against the 99.5% MVP target."""
    from backend.app.services.slo_service import get_slo_dashboard

    data = await get_slo_dashboard(session, window_days=days)
    return SLODashboardResponse(
        target_pct=data.target_pct,
        window_days=data.window_days,
        rolling_availability_pct=data.rolling_availability_pct,
        total_probes=data.total_probes,
        successful_probes=data.successful_probes,
        failed_probes=data.failed_probes,
        services=data.services,
        alert_active=data.alert_active,
        alert_message=data.alert_message,
        recent_alerts=[AvailabilityAlertItem(**a) for a in data.recent_alerts],
        daily_uptime=[SLODailyPoint(**d) for d in data.daily_uptime],
    )


@router.post("/slo/probes", response_model=HealthProbeResponse, status_code=status.HTTP_201_CREATED)
async def record_probe(
    body: HealthProbeRequest,
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Record a health-probe sample used for 30-day rolling availability."""
    from backend.app.services.slo_service import record_health_probe

    if not body.service_name or not body.service_name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="service_name is required",
        )

    probe = await record_health_probe(
        session,
        service_name=body.service_name.strip(),
        is_healthy=body.is_healthy,
        latency_ms=body.latency_ms,
        detail=body.detail,
    )
    await session.commit()
    return HealthProbeResponse(
        id=probe.id,
        service_name=probe.service_name,
        is_healthy=probe.is_healthy,
        probed_at=probe.probed_at.isoformat() if probe.probed_at else "",
    )


@router.post("/slo/evaluate-alert", response_model=SLOAlertEvaluateResponse)
async def evaluate_slo_alert(
    admin_identity: str = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Evaluate 30-day rolling availability and fire an alert when below 99.5%."""
    from backend.app.services.slo_service import evaluate_and_alert

    result = await evaluate_and_alert(session)
    await session.commit()
    return SLOAlertEvaluateResponse(
        breached=result["breached"],
        rolling_availability_pct=result["rolling_availability_pct"],
        target_pct=result["target_pct"],
        alert_id=result.get("alert_id"),
        message=result.get("message"),
    )

