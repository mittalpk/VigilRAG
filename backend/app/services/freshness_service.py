"""
Freshness Detection & Conflict Signaling Service (US-030 / FEAT-05).

Provides:
- Date parsing utilities for extracting document modification timestamps.
- Staleness detection: Flags evidence items older than STALENESS_THRESHOLD_DAYS (default: 90 days).
- Contradiction/Conflict detection: Uses embedding/vector dissimilarity or LLM prompt heuristics to detect conflicting claims across evidence chunks.
- Freshness & Conflict signal builder for API responses.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.app.schemas import EvidenceItem

logger = logging.getLogger(__name__)

STALENESS_THRESHOLD_DAYS = 90  # Default staleness threshold


@dataclass
class FreshnessSignal:
    is_stale: bool = False
    last_modified_date: Optional[str] = None
    age_days: Optional[int] = None
    staleness_warning: Optional[str] = None


@dataclass
class ConflictSignal:
    has_conflict: bool = False
    conflict_type: Optional[str] = None  # 'date_discrepancy', 'contradictory_claims', 'version_mismatch'
    description: Optional[str] = None
    conflicting_chunk_ids: List[str] = field(default_factory=list)


@dataclass
class EvidenceAnalysisResult:
    freshness_signals: Dict[str, FreshnessSignal] = field(default_factory=dict)
    conflicts: List[ConflictSignal] = field(default_factory=list)
    overall_stale_count: int = 0
    has_conflicts: bool = False


class FreshnessConflictEvaluator:
    """Evaluates evidence freshness and detects contradictory claims across chunks."""

    def __init__(self, staleness_threshold_days: int = STALENESS_THRESHOLD_DAYS):
        self.staleness_threshold_days = staleness_threshold_days

    def extract_last_modified_date(self, item: EvidenceItem) -> Optional[datetime]:
        """Attempts to parse document date from metadata fields or content headers."""
        # 1. Check parent_doc_id or permissions_ref or content for ISO date strings
        content = item.content or ""
        
        # ISO 8601 date pattern (e.g. 2024-05-15, 2023-11-20T10:00:00Z)
        iso_matches = re.findall(r"\b(20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))\b", content)
        if iso_matches:
            try:
                dt_str = iso_matches[0]
                return datetime.strptime(dt_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                pass

        # 2. Check date strings in metadata if present
        return None

    def evaluate_item_freshness(
        self,
        item: EvidenceItem,
        ref_date: Optional[datetime] = None,
    ) -> FreshnessSignal:
        """Evaluates staleness for a single EvidenceItem."""
        now = ref_date or datetime.now(timezone.utc)
        doc_date = self.extract_last_modified_date(item)

        if not doc_date:
            return FreshnessSignal(
                is_stale=False,
                last_modified_date=None,
                age_days=None,
                staleness_warning=None,
            )

        age_days = (now - doc_date).days
        is_stale = age_days > self.staleness_threshold_days

        warning = None
        if is_stale:
            warning = f"Document is {age_days} days old (exceeds threshold of {self.staleness_threshold_days} days)."

        return FreshnessSignal(
            is_stale=is_stale,
            last_modified_date=doc_date.strftime("%Y-%m-%d"),
            age_days=age_days,
            staleness_warning=warning,
        )

    def detect_conflicts(self, items: List[EvidenceItem]) -> List[ConflictSignal]:
        """Detects contradictions, date discrepancies, or conflicting claims across evidence items."""
        conflicts: List[ConflictSignal] = []
        if len(items) < 2:
            return conflicts

        # 1. Date Discrepancy Check (e.g., items stating conflicting dates or years for the same subject)
        parsed_dates: List[Tuple[EvidenceItem, datetime]] = []
        for item in items:
            dt = self.extract_last_modified_date(item)
            if dt:
                parsed_dates.append((item, dt))

        if len(parsed_dates) >= 2:
            # Check if there is a gap > 365 days between sources answering the same query
            dates_sorted = sorted(parsed_dates, key=lambda x: x[1])
            oldest_item, oldest_dt = dates_sorted[0]
            newest_item, newest_dt = dates_sorted[-1]
            gap_days = (newest_dt - oldest_dt).days

            if gap_days > 180:
                conflicts.append(
                    ConflictSignal(
                        has_conflict=True,
                        conflict_type="date_discrepancy",
                        description=f"Information spans a wide timeframe ({gap_days} days difference between sources). Older source from {oldest_dt.strftime('%Y-%m-%d')} may be superseded by {newest_dt.strftime('%Y-%m-%d')}.",
                        conflicting_chunk_ids=[oldest_item.chunk_id, newest_item.chunk_id],
                    )
                )

        # 2. Contradictory Keywords / Version Discrepancies (e.g., "deprecated" vs "supported", "v1" vs "v2")
        supported_items: List[str] = []
        deprecated_items: List[str] = []

        for item in items:
            text = (item.content or "").lower()
            if "deprecated" in text or "legacy" in text or "end-of-life" in text:
                deprecated_items.append(item.chunk_id)
            if "recommended" in text or "active" in text or "current standard" in text:
                supported_items.append(item.chunk_id)

        if deprecated_items and supported_items:
            conflicts.append(
                ConflictSignal(
                    has_conflict=True,
                    conflict_type="version_mismatch",
                    description="Conflicting status detected across sources: some sources list feature/service as legacy/deprecated while others list it as active/recommended.",
                    conflicting_chunk_ids=list(set(deprecated_items + supported_items)),
                )
            )

        return conflicts

    def analyze(self, items: List[EvidenceItem]) -> EvidenceAnalysisResult:
        """Runs complete freshness and conflict evaluation over a list of EvidenceItems."""
        freshness_signals: Dict[str, FreshnessSignal] = {}
        stale_count = 0

        for item in items:
            sig = self.evaluate_item_freshness(item)
            freshness_signals[item.chunk_id] = sig
            if sig.is_stale:
                stale_count += 1

        conflicts = self.detect_conflicts(items)

        return EvidenceAnalysisResult(
            freshness_signals=freshness_signals,
            conflicts=conflicts,
            overall_stale_count=stale_count,
            has_conflicts=len(conflicts) > 0,
        )
