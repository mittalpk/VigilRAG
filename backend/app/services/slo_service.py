"""
Availability SLO monitoring & alerting service (US-036 / NFR-008).

Tracks query-path uptime from health-probe samples against the 99.5% MVP
target and fires an alert when the 30-day rolling availability drops below
threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SLO_TARGET_PCT = float(os.getenv("AVAILABILITY_SLO_TARGET_PCT", "99.5"))
SLO_WINDOW_DAYS = int(os.getenv("AVAILABILITY_SLO_WINDOW_DAYS", "30"))
ALERT_CHANNEL = os.getenv("AVAILABILITY_ALERT_CHANNEL", "log")  # log | slack | email


@dataclass
class SLODashboardData:
    target_pct: float
    window_days: int
    rolling_availability_pct: float
    total_probes: int
    successful_probes: int
    failed_probes: int
    services: Dict[str, Dict[str, Any]]
    alert_active: bool
    alert_message: Optional[str] = None
    recent_alerts: List[Dict[str, Any]] = field(default_factory=list)
    daily_uptime: List[Dict[str, Any]] = field(default_factory=list)


async def record_health_probe(
    session: AsyncSession,
    *,
    service_name: str,
    is_healthy: bool,
    latency_ms: Optional[int] = None,
    detail: Optional[str] = None,
) -> Any:
    """Persist a single health-probe sample for SLO calculation."""
    from backend.app.models import HealthProbe

    probe = HealthProbe(
        id=f"hp-{uuid.uuid4().hex[:12]}",
        service_name=service_name,
        is_healthy=bool(is_healthy),
        latency_ms=latency_ms,
        detail=detail,
        probed_at=datetime.now(timezone.utc),
    )
    session.add(probe)
    await session.flush()
    return probe


def _emit_alert(message: str) -> Dict[str, Any]:
    """Deliver availability alert via configured channel (log / slack / email stub)."""
    payload = {
        "channel": ALERT_CHANNEL,
        "message": message,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    }
    if ALERT_CHANNEL == "slack":
        webhook = os.getenv("SLO_ALERT_SLACK_WEBHOOK", "")
        if webhook:
            try:
                import httpx
                httpx.post(webhook, json={"text": message}, timeout=5.0)
                payload["delivered"] = True
            except Exception as exc:
                logger.warning(f"Slack SLO alert delivery failed: {exc}")
                payload["delivered"] = False
                payload["error"] = str(exc)
        else:
            logger.warning("SLO_ALERT_SLACK_WEBHOOK not set — logging alert instead")
            logger.error(f"AVAILABILITY_SLO_ALERT: {message}")
            payload["delivered"] = False
    elif ALERT_CHANNEL == "email":
        # Production would integrate SMTP / SES; for MVP we log the alert payload.
        logger.error(f"AVAILABILITY_SLO_ALERT (email channel): {message}")
        payload["delivered"] = True
    else:
        logger.error(f"AVAILABILITY_SLO_ALERT: {message}")
        payload["delivered"] = True
    return payload


async def evaluate_and_alert(
    session: AsyncSession,
    *,
    target_pct: float = SLO_TARGET_PCT,
    window_days: int = SLO_WINDOW_DAYS,
) -> Dict[str, Any]:
    """
    Compute 30-day rolling availability; if below target, persist and emit an alert.
    Returns alert decision payload.
    """
    from backend.app.models import AvailabilityAlert

    dashboard = await get_slo_dashboard(session, target_pct=target_pct, window_days=window_days, include_alerts=False)
    breached = dashboard.rolling_availability_pct < target_pct and dashboard.total_probes > 0
    result: Dict[str, Any] = {
        "breached": breached,
        "rolling_availability_pct": dashboard.rolling_availability_pct,
        "target_pct": target_pct,
        "alert_id": None,
    }
    if not breached:
        return result

    message = (
        f"Availability SLO breach: {dashboard.rolling_availability_pct:.3f}% "
        f"< {target_pct}% over {window_days}-day rolling window "
        f"({dashboard.successful_probes}/{dashboard.total_probes} probes healthy)"
    )
    delivery = _emit_alert(message)
    alert = AvailabilityAlert(
        id=f"aa-{uuid.uuid4().hex[:12]}",
        alert_type="availability_slo_breach",
        message=message,
        rolling_availability_pct=dashboard.rolling_availability_pct,
        target_pct=target_pct,
        channel=ALERT_CHANNEL,
        delivered=bool(delivery.get("delivered", False)),
        created_at=datetime.now(timezone.utc),
    )
    session.add(alert)
    await session.flush()
    result["alert_id"] = alert.id
    result["message"] = message
    result["delivery"] = delivery
    return result


async def get_slo_dashboard(
    session: AsyncSession,
    *,
    target_pct: float = SLO_TARGET_PCT,
    window_days: int = SLO_WINDOW_DAYS,
    include_alerts: bool = True,
) -> SLODashboardData:
    """Build SLO dashboard payload from health_probes + availability_alerts."""
    from backend.app.models import AvailabilityAlert, HealthProbe

    since = datetime.now(timezone.utc) - timedelta(days=max(1, window_days))
    stmt = select(HealthProbe).where(HealthProbe.probed_at >= since).order_by(HealthProbe.probed_at.asc())
    res = await session.execute(stmt)
    probes = list(res.scalars().all())

    total = len(probes)
    successful = sum(1 for p in probes if p.is_healthy)
    failed = total - successful
    rolling = (100.0 * successful / total) if total else 100.0

    services: Dict[str, Dict[str, Any]] = {}
    daily: Dict[str, Dict[str, int]] = {}
    for p in probes:
        svc = services.setdefault(p.service_name, {"total": 0, "healthy": 0, "availability_pct": 100.0})
        svc["total"] += 1
        if p.is_healthy:
            svc["healthy"] += 1
        day = (p.probed_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        bucket = daily.setdefault(day, {"total": 0, "healthy": 0})
        bucket["total"] += 1
        if p.is_healthy:
            bucket["healthy"] += 1

    for svc in services.values():
        svc["availability_pct"] = round(100.0 * svc["healthy"] / svc["total"], 4) if svc["total"] else 100.0

    daily_uptime = [
        {
            "date": day,
            "availability_pct": round(100.0 * vals["healthy"] / vals["total"], 4) if vals["total"] else 100.0,
            "total_probes": vals["total"],
            "healthy_probes": vals["healthy"],
        }
        for day, vals in sorted(daily.items())
    ]

    alert_active = rolling < target_pct and total > 0
    alert_message = None
    if alert_active:
        alert_message = (
            f"30-day rolling availability {rolling:.3f}% is below the {target_pct}% MVP SLO target"
        )

    recent_alerts: List[Dict[str, Any]] = []
    if include_alerts:
        a_stmt = (
            select(AvailabilityAlert)
            .order_by(AvailabilityAlert.created_at.desc())
            .limit(10)
        )
        a_res = await session.execute(a_stmt)
        for a in a_res.scalars().all():
            recent_alerts.append(
                {
                    "id": a.id,
                    "alert_type": a.alert_type,
                    "message": a.message,
                    "rolling_availability_pct": a.rolling_availability_pct,
                    "target_pct": a.target_pct,
                    "channel": a.channel,
                    "delivered": a.delivered,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
            )

    return SLODashboardData(
        target_pct=target_pct,
        window_days=window_days,
        rolling_availability_pct=round(rolling, 4),
        total_probes=total,
        successful_probes=successful,
        failed_probes=failed,
        services=services,
        alert_active=alert_active,
        alert_message=alert_message,
        recent_alerts=recent_alerts,
        daily_uptime=daily_uptime,
    )
