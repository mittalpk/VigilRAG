"""
Test suite for US-004 Security Architecture Design Spike & ADR-001 Validator.
Tests identity signature verification (constant-time HMAC), permission cache expiration/restricted TTL=0 logic,
ACL chunk pre-filtering, zero over-exposure assertions, and ARB review sign-off validation.
Uses workspace-root imports: `from backend.app.services.security_spike_validator import ...`
"""

from datetime import datetime, timedelta, timezone
import pytest

from backend.app.services.security_spike_validator import (
    ARBApprovalStatus,
    ARBReviewRecord,
    ChunkRecord,
    PermissionCacheRecord,
    PermissionSecurityDesignValidator,
    SensitivityClassification,
)


@pytest.fixture
def sample_arb_review():
    return ARBReviewRecord(
        review_date="2026-07-23",
        ciso_name="Marcus Vance",
        lead_architect_name="Dr. Elena Rostova",
        governance_officer_name="Sarah Chen",
        status=ARBApprovalStatus.APPROVED,
        unresolved_high_severity_findings_count=0,
        signed_off=True,
    )


@pytest.fixture
def sample_chunks():
    return [
        ChunkRecord("c-01", "src-github-001", "Public code license", "public"),
        ChunkRecord("c-02", "src-github-001", "Core repo auth logic", "github:vigilrag/core-platform:read"),
        ChunkRecord("c-03", "src-wiki-001", "Exec financial strategy", "wiki:EXEC:exec-board-only"),
        ChunkRecord("c-04", "src-wiki-001", "Engineering design doc", "wiki:ENG:group-eng-staff"),
    ]


def test_arb_review_validation_success(sample_arb_review):
    validator = PermissionSecurityDesignValidator()
    res = validator.validate_arb_review(sample_arb_review, adr_document_exists=True)

    assert res.passed is True
    assert res.status == ARBApprovalStatus.APPROVED
    assert len(res.errors) == 0
    assert res.summary["ciso"] == "Marcus Vance"
    assert res.summary["trust_boundary_verified"] is True


def test_arb_review_validation_unresolved_high_severity_finding(sample_arb_review):
    sample_arb_review.unresolved_high_severity_findings_count = 1
    validator = PermissionSecurityDesignValidator()
    res = validator.validate_arb_review(sample_arb_review, adr_document_exists=True)

    assert res.passed is False
    assert any("unresolved high-severity findings" in err for err in res.errors)


def test_arb_review_validation_missing_adr_doc(sample_arb_review):
    validator = PermissionSecurityDesignValidator()
    res = validator.validate_arb_review(sample_arb_review, adr_document_exists=False)

    assert res.passed is False
    assert any("ADR-001 security architecture document missing" in err for err in res.errors)


def test_identity_signature_constant_time_hmac():
    validator = PermissionSecurityDesignValidator("my_secret_key")
    identity = "user:jane.doe@example.com"

    sig = validator.generate_identity_signature(identity)
    assert validator.verify_identity_signature(identity, sig) is True
    assert validator.verify_identity_signature("user:attacker@example.com", sig) is False


def test_permission_filtering_and_zero_over_exposure(sample_chunks):
    validator = PermissionSecurityDesignValidator()
    now = datetime.now(timezone.utc)

    # User Jane has access to core repo read and ENG staff wiki
    jane_cache = PermissionCacheRecord(
        requester_identity="user:jane.doe@example.com",
        source_id="src-github-001",
        access_level="read",
        granted_acl_refs={"github:vigilrag/core-platform:read", "wiki:ENG:group-eng-staff"},
        cached_at=now,
        ttl_seconds=900,
        sensitivity=SensitivityClassification.INTERNAL_SENSITIVE,
    )

    filtered = validator.filter_chunks_for_identity(sample_chunks, jane_cache)
    # Should get c-01 (public), c-02 (core-platform), c-04 (ENG wiki). Should NOT get c-03 (EXEC wiki)
    assert len(filtered) == 3
    assert {c.chunk_id for c in filtered} == {"c-01", "c-02", "c-04"}

    # Confirm over-exposure assertion passes for Jane
    assert validator.assert_zero_over_exposure(filtered, jane_cache.granted_acl_refs) is True

    # If c-03 was leaked, assertion raises ValueError
    with pytest.raises(ValueError, match="SECURITY VIOLATION"):
        validator.assert_zero_over_exposure(sample_chunks, jane_cache.granted_acl_refs)


def test_restricted_source_ttl_zero_override(sample_chunks):
    validator = PermissionSecurityDesignValidator()
    now = datetime.now(timezone.utc)

    # Restricted source always forces is_expired = True
    restricted_cache = PermissionCacheRecord(
        requester_identity="user:jane.doe@example.com",
        source_id="src-wiki-001",
        access_level="read",
        granted_acl_refs={"wiki:EXEC:exec-board-only"},
        cached_at=now,
        ttl_seconds=900,
        sensitivity=SensitivityClassification.RESTRICTED,
    )

    assert restricted_cache.is_expired is True
    # Expired restricted cache returns 0 chunks until live re-verification
    filtered = validator.filter_chunks_for_identity(sample_chunks, restricted_cache)
    assert len(filtered) == 0
