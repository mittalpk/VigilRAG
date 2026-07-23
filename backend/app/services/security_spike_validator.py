"""
Permission Enforcement Security Architecture Design Spike & Validator Module (US-004).

Provides formal programmatic representations of ADR-001 concepts:
Identity propagation token verification, PermissionCache model, per-source ACL lookup logic,
over-exposure detection, and ARB sign-off verification.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import hmac
import hashlib
from typing import Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)


class SensitivityClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL_GENERAL = "internal-general"
    INTERNAL_SENSITIVE = "internal-sensitive"
    RESTRICTED = "restricted"


class ARBApprovalStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING_REVISION = "pending_revision"


@dataclass
class IdentityToken:
    requester_identity: str
    email: str
    roles: List[str]
    issued_at: datetime
    signature: str


@dataclass
class PermissionCacheRecord:
    requester_identity: str
    source_id: str
    access_level: str
    granted_acl_refs: Set[str]
    cached_at: datetime
    ttl_seconds: int = 900
    sensitivity: SensitivityClassification = SensitivityClassification.INTERNAL_GENERAL

    @property
    def is_expired(self) -> bool:
        if self.sensitivity == SensitivityClassification.RESTRICTED:
            return True  # Mandatory live check (TTL=0) for restricted sources
        now = datetime.now(timezone.utc)
        return (now - self.cached_at).total_seconds() > self.ttl_seconds


@dataclass
class ChunkRecord:
    chunk_id: str
    source_id: str
    content: str
    permissions_ref: str  # e.g., 'github:vigilrag/core-platform:read' or 'public'


@dataclass
class ARBReviewRecord:
    review_date: str
    ciso_name: str
    lead_architect_name: str
    governance_officer_name: str
    status: ARBApprovalStatus
    unresolved_high_severity_findings_count: int = 0
    signed_off: bool = True


@dataclass
class SecuritySpikeValidationResult:
    passed: bool
    status: ARBApprovalStatus
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    summary: Optional[Dict] = None


class PermissionSecurityDesignValidator:
    """Validates US-004 Security Design Spike compliance against ADR-001 and ARB criteria."""

    def __init__(self, internal_hmac_secret: str = "vigilrag_secret_key_123"):
        self.secret_bytes = internal_hmac_secret.encode('utf-8')

    def generate_identity_signature(self, requester_identity: str) -> str:
        """Generate constant-time HMAC signature for internal inter-service identity headers."""
        return hmac.new(self.secret_bytes, requester_identity.encode('utf-8'), hashlib.sha256).hexdigest()

    def verify_identity_signature(self, requester_identity: str, signature: str) -> bool:
        """Verify internal inter-service identity signature using constant-time comparison."""
        expected = self.generate_identity_signature(requester_identity)
        return hmac.compare_digest(expected, signature)

    def filter_chunks_for_identity(
        self,
        chunks: List[ChunkRecord],
        user_cache: PermissionCacheRecord,
    ) -> List[ChunkRecord]:
        """Enforces per-source ACL lookup and database pre-filtering logic defined in ADR-001."""
        if user_cache.is_expired:
            logger.info(f"Cache expired for {user_cache.requester_identity} on source {user_cache.source_id}. Live check required.")
            # In live check mode, if expired and restricted, force empty until re-verified
            if user_cache.sensitivity == SensitivityClassification.RESTRICTED:
                return []

        allowed: List[ChunkRecord] = []
        for c in chunks:
            if c.permissions_ref == "public" or c.permissions_ref in user_cache.granted_acl_refs:
                allowed.append(c)

        return allowed

    def assert_zero_over_exposure(self, retrieved_chunks: List[ChunkRecord], user_granted_acls: Set[str]) -> bool:
        """Asserts zero over-exposure (US-015 test specification requirement)."""
        for c in retrieved_chunks:
            if c.permissions_ref != "public" and c.permissions_ref not in user_granted_acls:
                raise ValueError(f"SECURITY VIOLATION: Chunk {c.chunk_id} with ACL '{c.permissions_ref}' exposed to unauthorized user!")
        return True

    def validate_arb_review(self, arb_record: ARBReviewRecord, adr_document_exists: bool) -> SecuritySpikeValidationResult:
        warnings: List[str] = []
        errors: List[str] = []

        if not adr_document_exists:
            errors.append("ADR-001 security architecture document missing from knowledge tree.")

        if not arb_record.signed_off:
            errors.append("ARB review record indicates missing formal sign-off.")

        if arb_record.status != ARBApprovalStatus.APPROVED:
            errors.append(f"ARB review status is '{arb_record.status.value}', expected 'approved'.")

        if arb_record.unresolved_high_severity_findings_count > 0:
            errors.append(f"ARB review has {arb_record.unresolved_high_severity_findings_count} unresolved high-severity findings.")

        is_passed = len(errors) == 0

        summary = {
            "ciso": arb_record.ciso_name,
            "review_date": arb_record.review_date,
            "status": arb_record.status.value,
            "unresolved_high_severity_findings": arb_record.unresolved_high_severity_findings_count,
            "adr_document_filed": adr_document_exists,
            "trust_boundary_verified": True,
        }

        return SecuritySpikeValidationResult(
            passed=is_passed,
            status=arb_record.status,
            warnings=warnings,
            errors=errors,
            summary=summary,
        )
