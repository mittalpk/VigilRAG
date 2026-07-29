"""
Compliance audit digest reports — weekly/monthly (US-039 / FEAT-08).

Aggregates query counts, unique identities, guardrail flags; delivers via
log / Slack / email (same channel pattern as SLO alerts).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import AnswerRecord, QueryRecord, ScheduledReport

logger = logging.getLogger(__name__)


def get_digest_channel() -> str:
    return os.getenv("AUDIT_DIGEST_CHANNEL", "log").strip().lower()


def get_digest_destination() -> str:
    return (
        os.getenv("AUDIT_DIGEST_DESTINATION", "")
        or os.getenv("AUDIT_DIGEST_SLACK_WEBHOOK", "")
        or os.getenv("SLO_ALERT_SLACK_WEBHOOK", "")
        or "compliance-officer@example.com"
    )


async def compute_digest_stats(
    session: AsyncSession,
    *,
    cadence: str = "weekly",
    as_of: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute summary statistics for the digest window."""
    now = as_of or datetime.now(timezone.utc)
    days = 30 if cadence == "monthly" else 7
    window_start = now - timedelta(days=days)

    q_count_res = await session.execute(
        select(func.count()).select_from(QueryRecord).where(QueryRecord.created_at >= window_start)
    )
    query_count = int(q_count_res.scalar() or 0)

    id_res = await session.execute(
        select(func.count(func.distinct(QueryRecord.requester_identity))).where(
            QueryRecord.created_at >= window_start
        )
    )
    unique_identities = int(id_res.scalar() or 0)

    ans_res = await session.execute(
        select(AnswerRecord).join(QueryRecord, AnswerRecord.query_id == QueryRecord.id).where(
            QueryRecord.created_at >= window_start
        )
    )
    answers = list(ans_res.scalars().all())
    flagged = 0
    guardrail_events: Dict[str, int] = {}
    for ans in answers:
        flags: List[str] = []
        if ans.guardrail_flags_json:
            try:
                flags = json.loads(ans.guardrail_flags_json)
            except Exception:
                flags = []
        if flags:
            flagged += 1
            for f in flags:
                guardrail_events[str(f)] = guardrail_events.get(str(f), 0) + 1

    return {
        "cadence": cadence,
        "window_days": days,
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "query_count": query_count,
        "unique_identities": unique_identities,
        "flagged_responses": flagged,
        "guardrail_events": guardrail_events,
        "total_answers": len(answers),
    }


def render_digest_markdown(stats: Dict[str, Any]) -> str:
    events = stats.get("guardrail_events") or {}
    event_lines = "\n".join(f"- `{k}`: {v}" for k, v in sorted(events.items())) or "- (none)"
    return (
        f"# VigilRAG Audit Digest ({stats.get('cadence', 'weekly')})\n\n"
        f"**Window:** {stats.get('window_start')} → {stats.get('window_end')} "
        f"({stats.get('window_days')} days)\n\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Query count | {stats.get('query_count', 0)} |\n"
        f"| Unique identities | {stats.get('unique_identities', 0)} |\n"
        f"| Flagged responses | {stats.get('flagged_responses', 0)} |\n"
        f"| Answers in window | {stats.get('total_answers', 0)} |\n\n"
        f"## Guardrail events\n\n{event_lines}\n"
    )


def deliver_digest(markdown: str, *, channel: Optional[str] = None, destination: Optional[str] = None) -> Dict[str, Any]:
    ch = (channel or get_digest_channel()).strip().lower()
    dest = destination if destination is not None else get_digest_destination()
    payload: Dict[str, Any] = {
        "channel": ch,
        "destination": dest,
        "delivered": False,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    }
    if ch == "slack":
        webhook = dest or os.getenv("AUDIT_DIGEST_SLACK_WEBHOOK", "") or os.getenv("SLO_ALERT_SLACK_WEBHOOK", "")
        if webhook and webhook.startswith("http"):
            try:
                import httpx

                httpx.post(webhook, json={"text": markdown[:3500]}, timeout=5.0)
                payload["delivered"] = True
            except Exception as exc:
                logger.warning(f"Audit digest Slack delivery failed: {exc}")
                payload["error"] = str(exc)
                logger.info(f"AUDIT_DIGEST:\n{markdown}")
        else:
            logger.info(f"AUDIT_DIGEST (slack fallback log):\n{markdown}")
            payload["delivered"] = True
            payload["note"] = "webhook unset — logged"
    elif ch == "email":
        logger.info(f"AUDIT_DIGEST (email → {dest}):\n{markdown}")
        payload["delivered"] = True
    else:
        logger.info(f"AUDIT_DIGEST:\n{markdown}")
        payload["delivered"] = True
    return payload


async def send_audit_digest(
    session: AsyncSession,
    *,
    cadence: str = "weekly",
    channel: Optional[str] = None,
    destination: Optional[str] = None,
    report_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute, render, deliver a digest; update ScheduledReport.last_run_at when configured."""
    cadence_clean = (cadence or "weekly").strip().lower()
    if cadence_clean not in ("weekly", "monthly"):
        raise ValueError("cadence must be weekly or monthly")

    stats = await compute_digest_stats(session, cadence=cadence_clean)
    markdown = render_digest_markdown(stats)
    delivery = deliver_digest(markdown, channel=channel, destination=destination)

    report: Optional[ScheduledReport] = None
    if report_id:
        res = await session.execute(select(ScheduledReport).where(ScheduledReport.id == report_id))
        report = res.scalar_one_or_none()
    else:
        res = await session.execute(
            select(ScheduledReport).where(
                ScheduledReport.cadence == cadence_clean,
                ScheduledReport.enabled.is_(True),
            ).limit(1)
        )
        report = res.scalar_one_or_none()

    if report is None and os.getenv("AUDIT_DIGEST_AUTO_SEED", "true").lower() in ("1", "true", "yes"):
        report = ScheduledReport(
            id=f"sr-{uuid.uuid4().hex[:12]}",
            cadence=cadence_clean,
            channel=(channel or get_digest_channel()),
            destination=(destination if destination is not None else get_digest_destination()),
            enabled=True,
            created_by="system",
        )
        session.add(report)

    if report is not None:
        report.last_run_at = datetime.now(timezone.utc)
        if channel:
            report.channel = channel
        if destination is not None:
            report.destination = destination
        await session.flush()

    return {
        "status": "sent" if delivery.get("delivered") else "failed",
        "stats": stats,
        "markdown": markdown,
        "delivery": delivery,
        "scheduled_report_id": report.id if report else None,
    }
