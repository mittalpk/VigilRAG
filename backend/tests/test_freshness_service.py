"""
Unit and Integration Tests for US-030 Freshness Detection & Conflict Signaling Service.
"""

from datetime import datetime, timedelta, timezone
import pytest

from backend.app.schemas import EvidenceItem
from backend.app.services.freshness_service import (
    ConflictSignal,
    EvidenceAnalysisResult,
    FreshnessConflictEvaluator,
    FreshnessSignal,
)


@pytest.fixture
def evaluator():
    return FreshnessConflictEvaluator(staleness_threshold_days=90)


def test_freshness_evaluation_recent_document(evaluator):
    recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
    item = EvidenceItem(
        chunk_id="chk-001",
        content=f"Document updated on {recent_date} with current API specifications.",
        source_url="https://wiki.example.com/doc-1",
        relevance_score=0.95,
        source_id="confluence_wiki",
    )

    sig = evaluator.evaluate_item_freshness(item)
    assert sig.is_stale is False
    assert sig.last_modified_date == recent_date
    assert sig.age_days == 10
    assert sig.staleness_warning is None


def test_freshness_evaluation_stale_document(evaluator):
    stale_date = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d")
    item = EvidenceItem(
        chunk_id="chk-002",
        content=f"Legacy architecture document created on {stale_date}.",
        source_url="https://wiki.example.com/doc-2",
        relevance_score=0.80,
        source_id="confluence_wiki",
    )

    sig = evaluator.evaluate_item_freshness(item)
    assert sig.is_stale is True
    assert sig.last_modified_date == stale_date
    assert sig.age_days == 120
    assert "exceeds threshold of 90 days" in sig.staleness_warning


def test_conflict_detection_date_discrepancy(evaluator):
    old_date = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%d")
    new_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")

    item1 = EvidenceItem(
        chunk_id="chk-001",
        content=f"Service Auth specification as of {old_date}: uses OAuth1.",
        source_url="https://wiki.example.com/auth-v1",
        relevance_score=0.90,
        source_id="confluence_wiki",
    )
    item2 = EvidenceItem(
        chunk_id="chk-002",
        content=f"Service Auth specification updated on {new_date}: migrated to OAuth2.",
        source_url="https://wiki.example.com/auth-v2",
        relevance_score=0.92,
        source_id="confluence_wiki",
    )

    conflicts = evaluator.detect_conflicts([item1, item2])
    assert len(conflicts) == 1
    assert conflicts[0].has_conflict is True
    assert conflicts[0].conflict_type == "date_discrepancy"
    assert "chk-001" in conflicts[0].conflicting_chunk_ids
    assert "chk-002" in conflicts[0].conflicting_chunk_ids


def test_conflict_detection_version_mismatch(evaluator):
    item1 = EvidenceItem(
        chunk_id="chk-101",
        content="Endpoint POST /v1/auth is deprecated and marked for end-of-life.",
        source_url="https://wiki.example.com/deprecations",
        relevance_score=0.88,
        source_id="confluence_wiki",
    )
    item2 = EvidenceItem(
        chunk_id="chk-102",
        content="Endpoint POST /v1/auth is active and the recommended standard for authentication.",
        source_url="https://wiki.example.com/active-apis",
        relevance_score=0.85,
        source_id="confluence_wiki",
    )

    conflicts = evaluator.detect_conflicts([item1, item2])
    assert len(conflicts) >= 1
    version_conflicts = [c for c in conflicts if c.conflict_type == "version_mismatch"]
    assert len(version_conflicts) == 1
    assert "chk-101" in version_conflicts[0].conflicting_chunk_ids
    assert "chk-102" in version_conflicts[0].conflicting_chunk_ids


def test_analyze_full_pipeline(evaluator):
    stale_date = (datetime.now(timezone.utc) - timedelta(days=150)).strftime("%Y-%m-%d")
    recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")

    item1 = EvidenceItem(
        chunk_id="chk-1",
        content=f"Deprecated API spec dated {stale_date}.",
        source_url="https://wiki.example.com/stale",
        relevance_score=0.75,
        source_id="wiki",
    )
    item2 = EvidenceItem(
        chunk_id="chk-2",
        content=f"Active recommended API spec dated {recent_date}.",
        source_url="https://wiki.example.com/recent",
        relevance_score=0.95,
        source_id="wiki",
    )

    res: EvidenceAnalysisResult = evaluator.analyze([item1, item2])
    assert res.overall_stale_count == 1
    assert res.has_conflicts is True
    assert res.freshness_signals["chk-1"].is_stale is True
    assert res.freshness_signals["chk-2"].is_stale is False
