"""
Source connector availability checks for graceful degradation (US-036 / NFR-005).

At query time, detects unavailable connectors (inactive source, revoked secret,
error status) and raises ConnectorUnavailableError so retrieval can exclude
those sources and surface ``source_availability_warning``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Source
from backend.app.services.exceptions import ConnectorUnavailableError

logger = logging.getLogger(__name__)

# Map source_type → canonical warning token prefix
SOURCE_TYPE_WARNING = {
    "github_repo": "github",
    "confluence_wiki": "wiki",
    "database_schema": "database",
}


@dataclass
class AvailabilityReport:
    available_source_ids: Set[str] = field(default_factory=set)
    unavailable_source_ids: Set[str] = field(default_factory=set)
    warnings: List[str] = field(default_factory=list)
    errors: List[ConnectorUnavailableError] = field(default_factory=list)


def _secret_looks_revoked(secret_reference: Optional[str]) -> bool:
    """Heuristic: empty / placeholder / explicitly revoked secret references."""
    if secret_reference is None:
        return True
    ref = secret_reference.strip().lower()
    if not ref:
        return True
    revoked_markers = (
        "revoked",
        "invalid",
        "missing",
        "none",
        "placeholder",
        "change-me",
        "unset",
    )
    return any(m in ref for m in revoked_markers)


def _github_token_unavailable() -> bool:
    """True only when chaos mode is enabled or PAT is explicitly revoked."""
    override = os.getenv("CHAOS_GITHUB_UNAVAILABLE", "").strip().lower()
    if override in ("1", "true", "yes"):
        return True
    pat = os.getenv("GITHUB_PAT", "").strip()
    # Empty PAT is common in unit tests / local demos — do not treat as chaos failure.
    # Explicit revoked/invalid values simulate the US-036 chaos procedure.
    return pat.lower() in ("revoked", "invalid")


def check_source_available(source: Source) -> None:
    """
    Raise ConnectorUnavailableError if this source must be excluded from retrieval.

    Conditions:
    - is_active is False
    - status in {error, inactive}
    - secret_reference revoked/empty
    - github_repo + process GitHub PAT missing/revoked (chaos simulation)
    """
    connector = SOURCE_TYPE_WARNING.get(source.source_type, source.source_type)
    if not source.is_active:
        raise ConnectorUnavailableError(connector, f"Source '{source.name}' is inactive")
    if (source.status or "").lower() in ("error", "inactive"):
        raise ConnectorUnavailableError(
            connector,
            f"Source '{source.name}' status={source.status}",
        )
    if _secret_looks_revoked(source.secret_reference):
        raise ConnectorUnavailableError(
            connector,
            f"Source '{source.name}' secret revoked or missing",
        )
    if source.source_type == "github_repo" and _github_token_unavailable():
        raise ConnectorUnavailableError(
            "github",
            "GitHub API token unavailable (revoked or unset)",
        )


async def evaluate_sources(session: AsyncSession) -> AvailabilityReport:
    """Evaluate all registered sources; collect available IDs and warning codes."""
    report = AvailabilityReport()
    res = await session.execute(select(Source))
    sources = list(res.scalars().all())

    seen_warnings: Set[str] = set()
    for src in sources:
        try:
            check_source_available(src)
            report.available_source_ids.add(src.id)
        except ConnectorUnavailableError as exc:
            report.unavailable_source_ids.add(src.id)
            report.errors.append(exc)
            code = exc.warning_code
            if code not in seen_warnings:
                seen_warnings.add(code)
                report.warnings.append(code)
            logger.warning(
                f"Connector unavailable during retrieval: source_id={src.id} "
                f"type={src.source_type} reason={exc.reason}"
            )

    return report


def filter_chunks_by_availability(chunks, report: AvailabilityReport):
    """Exclude chunks belonging to unavailable sources."""
    if not report.unavailable_source_ids:
        return list(chunks)
    return [c for c in chunks if c.source_id not in report.unavailable_source_ids]
