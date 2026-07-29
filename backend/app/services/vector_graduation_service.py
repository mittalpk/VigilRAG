"""
Vector database graduation trigger evaluation (US-038 / FEAT-20 / Technology Architecture §6a).

Evaluates corpus size, query latency, filtering complexity, and operational load.
Decision rule: ≥2 signals met → recommend migration spike; else no-migration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Chunk

logger = logging.getLogger(__name__)

# Thresholds: US-038 AC numeric bounds reconciled with Technology Architecture §6a.
# Corpus: US-038 uses >500K (early warning); §6a cites ~1M+. We use 500K as the signal.
CORPUS_SIZE_THRESHOLD = int(os.getenv("VECTOR_GRAD_CORPUS_THRESHOLD", "500000"))
# Full-scan / retrieval p90 ms indicating pgvector degradation (US-038 AC)
PGVECTOR_FULLSCAN_P90_MS = float(os.getenv("VECTOR_GRAD_FULLSCAN_P90_MS", "500"))
# NFR-006 planning upper bound for e2e p50; graduation when p90 > 2× that bound
NFR006_P50_TARGET_MS = float(os.getenv("VECTOR_GRAD_NFR006_P50_MS", "6000"))
LATENCY_P90_THRESHOLD_MS = float(
    os.getenv("VECTOR_GRAD_LATENCY_P90_MS", str(NFR006_P50_TARGET_MS * 2))
)
# Index build time threshold (minutes) for operational-load signal
INDEX_BUILD_MINUTES_THRESHOLD = float(os.getenv("VECTOR_GRAD_INDEX_BUILD_MINUTES", "30"))
# Next evaluation default cadence (days) when no migration
NEXT_EVAL_DAYS = int(os.getenv("VECTOR_GRAD_NEXT_EVAL_DAYS", "90"))


@dataclass
class TriggerSignal:
    name: str
    met: bool
    value: Any
    threshold: Any
    rationale: str


@dataclass
class GraduationEvaluation:
    evaluated_at: str
    signals: List[TriggerSignal]
    signals_met: int
    decision: str  # "migrate" | "no_migration" | "escalate"
    recommendation: str
    next_evaluation_date: str
    current_backend: str
    dual_write_enabled: bool
    migration_plan: Optional[Dict[str, Any]] = None
    borderline: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluated_at": self.evaluated_at,
            "signals": [asdict(s) for s in self.signals],
            "signals_met": self.signals_met,
            "decision": self.decision,
            "recommendation": self.recommendation,
            "next_evaluation_date": self.next_evaluation_date,
            "current_backend": self.current_backend,
            "dual_write_enabled": self.dual_write_enabled,
            "migration_plan": self.migration_plan,
            "borderline": self.borderline,
        }


def _env_float(name: str, default: Optional[float] = None) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


async def evaluate_graduation_triggers(
    session: AsyncSession,
    *,
    latency_p90_ms: Optional[float] = None,
    retrieval_dominant: Optional[bool] = None,
    filtering_complexity: Optional[bool] = None,
    index_build_minutes: Optional[float] = None,
    operational_contention: Optional[bool] = None,
) -> GraduationEvaluation:
    """
    Evaluate Technology Architecture §6a / US-038 trigger criteria.

    Measurement overrides may be supplied explicitly (tests / PI planning inputs)
    or via env vars (VECTOR_GRAD_MEASURED_*).
    """
    # ── Corpus size ─────────────────────────────────────────────────────────
    cnt_res = await session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.deleted_at.is_(None))
    )
    corpus_size = int(cnt_res.scalar() or 0)
    # Also consider measured full-scan p90 if provided
    fullscan_p90 = _env_float("VECTOR_GRAD_MEASURED_FULLSCAN_P90_MS", None)
    corpus_met = corpus_size > CORPUS_SIZE_THRESHOLD or (
        fullscan_p90 is not None and fullscan_p90 > PGVECTOR_FULLSCAN_P90_MS and corpus_size > CORPUS_SIZE_THRESHOLD * 0.5
    )
    corpus_signal = TriggerSignal(
        name="corpus_size",
        met=corpus_met,
        value={"chunk_count": corpus_size, "fullscan_p90_ms": fullscan_p90},
        threshold={"chunk_count": CORPUS_SIZE_THRESHOLD, "fullscan_p90_ms": PGVECTOR_FULLSCAN_P90_MS},
        rationale=(
            f"Corpus has {corpus_size:,} active chunks "
            f"(threshold >{CORPUS_SIZE_THRESHOLD:,}); "
            f"full-scan p90={fullscan_p90}ms (threshold >{PGVECTOR_FULLSCAN_P90_MS}ms)"
        ),
    )

    # ── Query latency ───────────────────────────────────────────────────────
    measured_p90 = latency_p90_ms if latency_p90_ms is not None else _env_float(
        "VECTOR_GRAD_MEASURED_LATENCY_P90_MS",
        # Default to US-036 load-test observed p90 when unset (pilot baseline)
        3620.0,
    )
    ret_dom = (
        retrieval_dominant
        if retrieval_dominant is not None
        else _env_bool("VECTOR_GRAD_RETRIEVAL_DOMINANT", False)
    )
    latency_met = bool(
        measured_p90 is not None
        and measured_p90 > LATENCY_P90_THRESHOLD_MS
        and ret_dom
    )
    latency_signal = TriggerSignal(
        name="query_latency",
        met=latency_met,
        value={"p90_ms": measured_p90, "retrieval_dominant": ret_dom},
        threshold={"p90_ms": LATENCY_P90_THRESHOLD_MS, "requires_retrieval_dominant": True},
        rationale=(
            f"Query-path p90={measured_p90}ms vs threshold >{LATENCY_P90_THRESHOLD_MS}ms "
            f"(2× NFR-006 p50={NFR006_P50_TARGET_MS}ms); retrieval_dominant={ret_dom}"
        ),
    )

    # ── Filtering complexity ────────────────────────────────────────────────
    filter_complex = (
        filtering_complexity
        if filtering_complexity is not None
        else _env_bool("VECTOR_GRAD_FILTERING_COMPLEXITY", False)
    )
    filter_signal = TriggerSignal(
        name="filtering_complexity",
        met=bool(filter_complex),
        value={"rich_metadata_prefilter_required": filter_complex},
        threshold={"rich_metadata_prefilter_required": True},
        rationale=(
            "Rich per-tenant/per-classification ANN pre-filtering required"
            if filter_complex
            else "Current retrieval uses keyword candidate pre-filter + post-hoc permission filter; "
            "dedicated ANN metadata planners not yet required"
        ),
    )

    # ── Operational load ────────────────────────────────────────────────────
    build_mins = (
        index_build_minutes
        if index_build_minutes is not None
        else _env_float("VECTOR_GRAD_MEASURED_INDEX_BUILD_MINUTES", 0.0)
    ) or 0.0
    contention = (
        operational_contention
        if operational_contention is not None
        else _env_bool("VECTOR_GRAD_OPERATIONAL_CONTENTION", False)
    )
    ops_met = build_mins > INDEX_BUILD_MINUTES_THRESHOLD or contention
    ops_signal = TriggerSignal(
        name="operational_load",
        met=ops_met,
        value={"index_build_minutes": build_mins, "postgres_contention": contention},
        threshold={"index_build_minutes": INDEX_BUILD_MINUTES_THRESHOLD, "postgres_contention": True},
        rationale=(
            f"Index build={build_mins}min (threshold >{INDEX_BUILD_MINUTES_THRESHOLD}min); "
            f"postgres_contention={contention}"
        ),
    )

    signals = [corpus_signal, latency_signal, filter_signal, ops_signal]
    met_count = sum(1 for s in signals if s.met)

    # Borderline: exactly one clear met + one near-threshold
    borderline = False
    if met_count == 1:
        # Near corpus threshold (within 20%)
        if not corpus_met and corpus_size >= int(CORPUS_SIZE_THRESHOLD * 0.8):
            borderline = True
        if not latency_met and measured_p90 and measured_p90 >= LATENCY_P90_THRESHOLD_MS * 0.8:
            borderline = True

    now = datetime.now(timezone.utc)
    next_eval = (now + timedelta(days=NEXT_EVAL_DAYS)).date().isoformat()
    current_backend = os.getenv("VECTOR_SEARCH_BACKEND", "pgvector")
    dual = _env_bool("VECTOR_SEARCH_DUAL_WRITE", False)

    migration_plan = None
    if met_count >= 2:
        decision = "migrate"
        recommendation = (
            "≥2 graduation signals met — open a PI-level spike to migrate to a dedicated "
            "vector DB (Qdrant preferred for self-hosted enterprise; Weaviate for SaaS)."
        )
        migration_plan = build_migration_plan(target="qdrant")
    elif borderline:
        decision = "escalate"
        recommendation = (
            "Borderline signals detected (1 met + 1 near threshold). Escalate to the "
            "AI Solutions Architect for a judgment call; do not auto-migrate."
        )
    else:
        decision = "no_migration"
        recommendation = (
            f"Fewer than 2 graduation signals met ({met_count}/4). Remain on pgvector; "
            f"re-evaluate by {next_eval}."
        )

    return GraduationEvaluation(
        evaluated_at=now.isoformat(),
        signals=signals,
        signals_met=met_count,
        decision=decision,
        recommendation=recommendation,
        next_evaluation_date=next_eval,
        current_backend=current_backend,
        dual_write_enabled=dual,
        migration_plan=migration_plan,
        borderline=borderline,
    )


def build_migration_plan(target: str = "qdrant") -> Dict[str, Any]:
    """Documented migration steps produced when ≥2 signals are met."""
    return {
        "target_vector_db": target,
        "steps": [
            "1. Provision target vector DB (Qdrant cluster or Weaviate cloud) and set QDRANT_URL.",
            "2. Deploy VectorSearchBackend dual-write: VECTOR_SEARCH_DUAL_WRITE=true (reads=pgvector).",
            "3. Run scripts/migrate_vector_db.py --target qdrant to backfill all Chunk embeddings.",
            "4. Validate counts (abort if mismatch > 0.1%).",
            "5. Sample search consistency via DualWriteVectorSearchBackend.compare_search_consistency.",
            "6. Cut over reads: VECTOR_SEARCH_BACKEND=qdrant; disable dual-write after soak.",
            "7. Confirm latency improvement via OTel retrieval spans; verify zero data loss.",
            "8. Rollback plan: set VECTOR_SEARCH_BACKEND=pgvector (Postgres remains source of truth).",
        ],
        "data_backfill": "scripts/migrate_vector_db.py reads Chunk rows and upserts into target",
        "rollback": "Revert VECTOR_SEARCH_BACKEND=pgvector; Postgres chunk table unchanged",
        "acceptance": [
            "chunk count match within 0.1%",
            "sample search Jaccard ≥ 0.8 during dual-write",
            "retrieval p90 improved vs pre-cutover baseline",
        ],
    }


async def validate_migration_counts(
    source_count: int,
    target_count: int,
    max_mismatch_ratio: float = 0.001,
) -> Dict[str, Any]:
    """Abort cutover if count mismatch exceeds 0.1% (US-038 edge case)."""
    if source_count == 0 and target_count == 0:
        return {"ok": True, "mismatch_ratio": 0.0, "source_count": 0, "target_count": 0}
    denom = max(source_count, 1)
    mismatch = abs(source_count - target_count) / float(denom)
    return {
        "ok": mismatch <= max_mismatch_ratio,
        "mismatch_ratio": round(mismatch, 6),
        "source_count": source_count,
        "target_count": target_count,
        "max_mismatch_ratio": max_mismatch_ratio,
    }
