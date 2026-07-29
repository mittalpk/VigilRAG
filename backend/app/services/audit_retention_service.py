"""
Audit retention enforcement — archive then delete (US-039 / NFR-004).

Transactional batches: archive Query+Answer+Evidence into ``archived_queries``,
then delete from hot ``queries`` (CASCADE). Partial failure rolls back the batch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import (
    AnswerRecord,
    ArchivedQuery,
    EvidenceItemRecord,
    QueryRecord,
    RetentionRun,
)

logger = logging.getLogger(__name__)


def get_retention_days() -> int:
    return max(1, int(os.getenv("AUDIT_RETENTION_DAYS", "365")))


async def enforce_audit_retention(
    session: AsyncSession,
    *,
    retention_days: Optional[int] = None,
    batch_size: int = 100,
) -> Dict[str, Any]:
    """
    Archive then delete queries older than the retention window.

    Returns a summary dict including retention_run_id and records_archived.
    """
    days = retention_days if retention_days is not None else get_retention_days()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    run_id = f"rr-{uuid.uuid4().hex[:12]}"

    run = RetentionRun(
        id=run_id,
        started_at=now,
        status="running",
        cutoff_at=cutoff,
        records_archived=0,
        retention_days=days,
    )
    session.add(run)
    await session.flush()

    total_archived = 0
    try:
        while True:
            stmt = (
                select(QueryRecord)
                .where(QueryRecord.created_at < cutoff)
                .order_by(QueryRecord.created_at.asc())
                .limit(batch_size)
            )
            res = await session.execute(stmt)
            batch: List[QueryRecord] = list(res.scalars().all())
            if not batch:
                break

            # Single transaction per batch — no partial archival
            for q in batch:
                ans_res = await session.execute(
                    select(AnswerRecord).where(AnswerRecord.query_id == q.id).limit(1)
                )
                ans = ans_res.scalar_one_or_none()
                ev_res = await session.execute(
                    select(EvidenceItemRecord).where(EvidenceItemRecord.query_id == q.id)
                )
                evidence = list(ev_res.scalars().all())
                evidence_payload = [
                    {
                        "id": e.id,
                        "chunk_id": e.chunk_id,
                        "source_id": e.source_id,
                        "source_url": e.source_url,
                        "relevance_score": e.relevance_score,
                        "rerank_score": e.rerank_score,
                        "used_in_answer": e.used_in_answer,
                    }
                    for e in evidence
                ]
                archive = ArchivedQuery(
                    id=q.id,
                    requester_identity=q.requester_identity,
                    query_text=q.query_text,
                    trace_id=q.trace_id,
                    original_created_at=q.created_at or now,
                    answer_text=ans.answer_text if ans else None,
                    groundedness_score=ans.groundedness_score if ans else None,
                    guardrail_flags_json=(ans.guardrail_flags_json if ans else "[]"),
                    evidence_json=json.dumps(evidence_payload),
                    archived_at=now,
                    retention_run_id=run_id,
                )
                session.add(archive)
                for e in evidence:
                    await session.delete(e)
                if ans is not None:
                    await session.delete(ans)
                await session.delete(q)

            total_archived += len(batch)
            await session.flush()

        run.status = "success"
        run.records_archived = total_archived
        run.finished_at = datetime.now(timezone.utc)
        await session.flush()
        logger.info(f"Retention run {run_id}: archived {total_archived} queries (cutoff={cutoff.isoformat()})")
        return {
            "retention_run_id": run_id,
            "status": "success",
            "records_archived": total_archived,
            "cutoff_at": cutoff.isoformat(),
            "retention_days": days,
        }
    except Exception as exc:
        await session.rollback()
        # Re-open run failure record in a clean state
        logger.error(f"Retention run {run_id} failed: {exc}")
        try:
            fail = RetentionRun(
                id=run_id,
                started_at=now,
                finished_at=datetime.now(timezone.utc),
                status="failed",
                cutoff_at=cutoff,
                records_archived=0,
                error_message=str(exc)[:2000],
                retention_days=days,
            )
            session.add(fail)
            await session.flush()
        except Exception as nested:
            logger.error(f"Could not persist retention failure log: {nested}")
        return {
            "retention_run_id": run_id,
            "status": "failed",
            "records_archived": 0,
            "cutoff_at": cutoff.isoformat(),
            "retention_days": days,
            "error": str(exc),
        }


async def get_retention_status(session: AsyncSession) -> Dict[str, Any]:
    """Return configured policy and latest retention run."""
    days = get_retention_days()
    stmt = select(RetentionRun).order_by(RetentionRun.started_at.desc()).limit(5)
    res = await session.execute(stmt)
    runs = list(res.scalars().all())
    latest = runs[0] if runs else None
    return {
        "retention_days": days,
        "latest_run": (
            {
                "id": latest.id,
                "status": latest.status,
                "started_at": latest.started_at.isoformat() if latest.started_at else None,
                "finished_at": latest.finished_at.isoformat() if latest.finished_at else None,
                "records_archived": latest.records_archived,
                "cutoff_at": latest.cutoff_at.isoformat() if latest.cutoff_at else None,
                "error_message": latest.error_message,
            }
            if latest
            else None
        ),
        "recent_runs": [
            {
                "id": r.id,
                "status": r.status,
                "records_archived": r.records_archived,
                "started_at": r.started_at.isoformat() if r.started_at else None,
            }
            for r in runs
        ],
    }
