"""
Cost-per-query calculation & aggregation service (US-036 / NFR-009).

Computes estimated USD cost from OTel token attributes (llm.input_tokens /
llm.output_tokens × published Gemini Flash / Pro pricing) and persists
query_costs rows for the admin cost dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Published Gemini API pricing (USD per 1M tokens). Overridable via env for rate changes.
# Source: Google AI Gemini pricing page (Flash / Pro families).
DEFAULT_MODEL_PRICING_USD_PER_1M: Dict[str, Dict[str, float]] = {
    "gemini-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}

FLASH_ALIASES = {"gemini-flash", "gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.5-flash"}
PRO_ALIASES = {"gemini-pro", "gemini-1.5-pro", "gemini-2.5-pro"}


def _pricing_table() -> Dict[str, Dict[str, float]]:
    """Merge defaults with optional env overrides (JSON not required — per-key env)."""
    table = {k: dict(v) for k, v in DEFAULT_MODEL_PRICING_USD_PER_1M.items()}
    flash_in = os.getenv("GEMINI_FLASH_INPUT_PRICE_PER_1M")
    flash_out = os.getenv("GEMINI_FLASH_OUTPUT_PRICE_PER_1M")
    pro_in = os.getenv("GEMINI_PRO_INPUT_PRICE_PER_1M")
    pro_out = os.getenv("GEMINI_PRO_OUTPUT_PRICE_PER_1M")
    if flash_in:
        for alias in FLASH_ALIASES:
            table.setdefault(alias, {"input": 0.075, "output": 0.30})["input"] = float(flash_in)
    if flash_out:
        for alias in FLASH_ALIASES:
            table.setdefault(alias, {"input": 0.075, "output": 0.30})["output"] = float(flash_out)
    if pro_in:
        for alias in PRO_ALIASES:
            table.setdefault(alias, {"input": 1.25, "output": 5.00})["input"] = float(pro_in)
    if pro_out:
        for alias in PRO_ALIASES:
            table.setdefault(alias, {"input": 1.25, "output": 5.00})["output"] = float(pro_out)
    return table


def normalize_model_family(model: str) -> str:
    """Map concrete model ids to Flash / Pro family labels for breakdown charts."""
    m = (model or "").strip().lower()
    if m in FLASH_ALIASES or "flash" in m:
        return "Flash"
    if m in PRO_ALIASES or "pro" in m:
        return "Pro"
    return "Other"


def calculate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    model: str = "gemini-1.5-pro",
) -> float:
    """
    cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
    using the model's published per-1M-token rates.
    """
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token counts must be non-negative")

    table = _pricing_table()
    key = (model or "gemini-1.5-pro").strip().lower()
    rates = table.get(key)
    if rates is None:
        # Fuzzy match on family
        family = normalize_model_family(key)
        if family == "Flash":
            rates = table.get("gemini-flash", {"input": 0.075, "output": 0.30})
        elif family == "Pro":
            rates = table.get("gemini-pro", {"input": 1.25, "output": 5.00})
        else:
            rates = {"input": 1.25, "output": 5.00}
            logger.warning(f"Unknown model '{model}' — using Pro pricing as conservative default")

    cost = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000.0
    return round(cost, 8)


@dataclass
class CostSummary:
    total_cost_usd: float
    total_queries: int
    avg_cost_per_query_usd: float
    cost_by_model: Dict[str, float]
    daily_trend: List[Dict[str, Any]]
    pi_total_cost_usd: float
    alert_spike: bool
    spike_message: Optional[str] = None


async def record_query_cost(
    session: AsyncSession,
    *,
    query_id: str,
    trace_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Optional[float] = None,
) -> Any:
    """Persist a QueryCost row derived from OTel token attributes."""
    from backend.app.models import QueryCost

    estimated = cost_usd if cost_usd is not None else calculate_cost_usd(input_tokens, output_tokens, model)
    record = QueryCost(
        id=f"qc-{uuid.uuid4().hex[:12]}",
        query_id=query_id,
        trace_id=trace_id,
        llm_model=model,
        model_family=normalize_model_family(model),
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        estimated_cost_usd=estimated,
        created_at=datetime.now(timezone.utc),
    )
    session.add(record)
    await session.flush()
    return record


async def get_cost_dashboard(
    session: AsyncSession,
    *,
    days: int = 30,
    spike_multiplier: float = 3.0,
) -> CostSummary:
    """Aggregate query_costs for the admin Cost Dashboard."""
    from backend.app.models import QueryCost

    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    stmt = select(QueryCost).where(QueryCost.created_at >= since).order_by(QueryCost.created_at.asc())
    res = await session.execute(stmt)
    rows: List[Any] = list(res.scalars().all())

    total_cost = sum(float(r.estimated_cost_usd or 0.0) for r in rows)
    total_queries = len(rows)
    avg = (total_cost / total_queries) if total_queries else 0.0

    by_model: Dict[str, float] = {}
    daily: Dict[str, Dict[str, float]] = {}
    for r in rows:
        family = r.model_family or normalize_model_family(r.llm_model)
        by_model[family] = by_model.get(family, 0.0) + float(r.estimated_cost_usd or 0.0)
        day_key = (r.created_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        bucket = daily.setdefault(day_key, {"cost_usd": 0.0, "queries": 0})
        bucket["cost_usd"] += float(r.estimated_cost_usd or 0.0)
        bucket["queries"] += 1

    daily_trend = [
        {
            "date": day,
            "total_cost_usd": round(vals["cost_usd"], 6),
            "query_count": int(vals["queries"]),
            "avg_cost_per_query_usd": round(vals["cost_usd"] / vals["queries"], 8) if vals["queries"] else 0.0,
        }
        for day, vals in sorted(daily.items())
    ]

    # PI window approximation: last 90 days (or configured)
    pi_days = int(os.getenv("COST_PI_WINDOW_DAYS", "90"))
    pi_since = datetime.now(timezone.utc) - timedelta(days=pi_days)
    pi_stmt = select(func.coalesce(func.sum(QueryCost.estimated_cost_usd), 0.0)).where(
        QueryCost.created_at >= pi_since
    )
    pi_res = await session.execute(pi_stmt)
    pi_total = float(pi_res.scalar() or 0.0)

    alert_spike = False
    spike_message = None
    if len(daily_trend) >= 2:
        latest = daily_trend[-1]["avg_cost_per_query_usd"]
        prior_avgs = [d["avg_cost_per_query_usd"] for d in daily_trend[:-1] if d["query_count"] > 0]
        if prior_avgs:
            baseline = sum(prior_avgs) / len(prior_avgs)
            if baseline > 0 and latest > baseline * spike_multiplier:
                alert_spike = True
                spike_message = (
                    f"Cost spike detected: latest day avg ${latest:.6f}/query "
                    f"exceeds {spike_multiplier:.0f}× baseline ${baseline:.6f}/query"
                )

    return CostSummary(
        total_cost_usd=round(total_cost, 6),
        total_queries=total_queries,
        avg_cost_per_query_usd=round(avg, 8),
        cost_by_model={k: round(v, 6) for k, v in by_model.items()},
        daily_trend=daily_trend,
        pi_total_cost_usd=round(pi_total, 6),
        alert_spike=alert_spike,
        spike_message=spike_message,
    )


def cost_from_otel_span_attributes(attributes: Dict[str, Any]) -> Tuple[str, int, int, float]:
    """Extract model/tokens/cost from an OTel span attribute dict (US-028)."""
    model = str(attributes.get("llm.model") or attributes.get("gen_ai.request.model") or "gemini-1.5-pro")
    input_tokens = int(attributes.get("llm.input_tokens") or attributes.get("gen_ai.usage.input_tokens") or 0)
    output_tokens = int(attributes.get("llm.output_tokens") or attributes.get("gen_ai.usage.output_tokens") or 0)
    return model, input_tokens, output_tokens, calculate_cost_usd(input_tokens, output_tokens, model)
