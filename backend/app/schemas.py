"""
Hybrid Retrieval, Evidence Types & Audit Schemas (US-008 / US-018 / US-022).

Defines Pydantic models and schemas for hybrid retrieval query requests and responses,
evaluation run persistence, and audit logging.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class KnowledgeQueryRequest(BaseModel):
    query: str = Field(..., description="Natural language search query")
    requester_identity: Optional[str] = Field("user@example.com", description="Identity of requester for permission filtering")
    top_k: int = Field(5, ge=1, le=20, description="Number of top evidence items to return")
    target_systems: Optional[List[str]] = Field(None, description="Optional system filter (e.g. ['confluence', 'code_repos'])")


class EvidenceItem(BaseModel):
    chunk_id: str
    content: str
    source_url: str
    relevance_score: float
    source_id: str
    parent_doc_id: Optional[str] = None
    references: List[str] = Field(default_factory=list)
    rerank_score: Optional[float] = None
    permissions_ref: str = "public"
    is_stale: bool = False
    last_modified_date: Optional[str] = None
    staleness_warning: Optional[str] = None


class ConflictSignalSchema(BaseModel):
    has_conflict: bool = True
    conflict_type: str
    description: str
    conflicting_chunk_ids: List[str] = Field(default_factory=list)


class HybridRetrievalResponse(BaseModel):
    evidence: List[EvidenceItem]
    trace_id: str
    query_id: str  # GAP-F01: Required by feedback capture (US-019) to link ratings to the correct query record
    execution_time_ms: int
    query: str
    total_retrieved: int
    stale_count: int = 0
    conflicts: List[ConflictSignalSchema] = Field(default_factory=list)
    # US-036 / NFR-005: graceful degradation when a source connector is unavailable
    source_availability_warning: List[str] = Field(default_factory=list)


class EvaluationRunResponse(BaseModel):
    id: str
    pipeline_version: str
    dataset_version: str
    total_cases: int
    faithfulness: float
    context_precision: float
    context_recall: float
    answer_relevancy: float
    passed_threshold: bool
    run_at: Any
    details: Optional[List[Dict[str, Any]]] = None


class EvaluationRunListResponse(BaseModel):
    items: List[EvaluationRunResponse]
    total: int
    page: int
    size: int


# ── Audit Log Schemas (US-018) ──────────────────────────────────────────────

class AuditEvidenceItem(BaseModel):
    id: Optional[str] = None
    chunk_id: str
    content_excerpt: str
    source_url: Optional[str] = None
    relevance_score: Optional[float] = None
    used_in_answer: bool = True
    permission_denied: bool = False


class AuditQueryItem(BaseModel):
    query_id: str
    requester_identity: str
    text: str
    timestamp: str
    answer_text: Optional[str] = None
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    groundedness_score: Optional[float] = None
    guardrail_flags: List[str] = Field(default_factory=list)


class AuditQueryListResponse(BaseModel):
    items: List[AuditQueryItem]
    total: int
    page: int
    per_page: int


class AuditQueryDetailResponse(AuditQueryItem):
    evidence_items: List[AuditEvidenceItem] = Field(default_factory=list)
    truncated: bool = False


# ── Feedback Schemas (US-019) ───────────────────────────────────────────────

class FeedbackCreateRequest(BaseModel):
    query_id: str = Field(..., description="Target query ID being rated")
    rating: str = Field(..., description="Rating: 'positive' or 'negative'")
    comment: Optional[str] = Field(None, max_length=500, description="Optional free-text feedback comment")


class FeedbackResponse(BaseModel):
    received: bool = True
    feedback_id: str
    query_id: str
    rating: str
    message: str = "Feedback saved successfully"


# ── Feedback Review Schemas (US-020) ───────────────────────────────────────

class FeedbackReviewItemResponse(BaseModel):
    id: str
    feedback_id: Optional[str] = None
    query_id: str
    requester_identity: str
    query_text: str
    answer_text: Optional[str] = None
    user_comment: Optional[str] = None
    rating: str
    status: str
    golden_answer: Optional[str] = None
    reviewed_by: Optional[str] = None
    created_at: str


class FeedbackReviewListResponse(BaseModel):
    items: List[FeedbackReviewItemResponse]
    total: int


# ── Source Registration Schemas (US-031) ───────────────────────────────────

class SourceTypeInfo(BaseModel):
    type_id: str
    display_name: str
    description: str
    supported: bool = True


class SourceCreateRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Display name for the source")
    source_type: str = Field(..., description="Source connector type (github_repo, confluence_wiki, database_schema)")
    endpoint_url: str = Field(..., description="Connection reference / repository URL")
    secret_reference: str = Field(..., description="Key Vault secret reference name (not raw credential)")
    owner_email: str = Field(..., description="Owner email for ACL and notifications")
    sensitivity_level: str = Field("internal-general", description="Sensitivity classification: public, internal-general, confidential, restricted")
    sensitivity_signed_off: bool = Field(False, description="Whether sensitivity classification has been signed off")
    refresh_cadence_minutes: int = Field(1440, ge=15, description="Refresh cadence in minutes (default 1440 = 24 hours)")
    indexing_scope: Optional[str] = Field("*", description="Path filter / glob scope for indexing")


class SourceUpdateRequest(BaseModel):
    name: Optional[str] = None
    endpoint_url: Optional[str] = None
    secret_reference: Optional[str] = None
    owner_email: Optional[str] = None
    sensitivity_level: Optional[str] = None
    sensitivity_signed_off: Optional[bool] = None
    refresh_cadence_minutes: Optional[int] = None
    indexing_scope: Optional[str] = None
    is_active: Optional[bool] = None


class SourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    endpoint_url: str
    secret_reference: str
    owner_email: str
    sensitivity_level: str
    sensitivity_signed_off: bool
    refresh_cadence_minutes: int
    status: str
    indexing_scope: Optional[str] = "*"
    is_active: bool
    created_at: str
    updated_at: str
    last_indexed_at: Optional[str] = None


class SourceListResponse(BaseModel):
    items: List[SourceResponse]
    total: int
    page: int
    size: int


class FeedbackActionRequest(BaseModel):
    action: str = Field(..., description="Action: 'promote', 'dismiss', or 'needs_investigation'")
    golden_answer: Optional[str] = Field(None, description="Expected golden answer when promoting to EvaluationCase")


# ── Cost Dashboard Schemas (US-036 / NFR-009) ───────────────────────────────

class CostDailyPoint(BaseModel):
    date: str
    total_cost_usd: float
    query_count: int
    avg_cost_per_query_usd: float


class CostDashboardResponse(BaseModel):
    total_cost_usd: float
    total_queries: int
    avg_cost_per_query_usd: float
    cost_by_model: Dict[str, float]
    daily_trend: List[CostDailyPoint]
    pi_total_cost_usd: float
    alert_spike: bool = False
    spike_message: Optional[str] = None
    window_days: int = 30


class QueryCostRecordRequest(BaseModel):
    query_id: str = Field(..., description="Query ID associated with the LLM call")
    trace_id: str = Field(..., description="OTel / request trace ID")
    model: str = Field(..., description="LLM model id (e.g. gemini-1.5-pro, gemini-flash)")
    input_tokens: int = Field(..., ge=0)
    output_tokens: int = Field(..., ge=0)


class QueryCostRecordResponse(BaseModel):
    id: str
    query_id: str
    estimated_cost_usd: float
    model_family: str


# ── SLO Dashboard Schemas (US-036 / NFR-008) ────────────────────────────────

class SLODailyPoint(BaseModel):
    date: str
    availability_pct: float
    total_probes: int
    healthy_probes: int


class AvailabilityAlertItem(BaseModel):
    id: str
    alert_type: str
    message: str
    rolling_availability_pct: float
    target_pct: float
    channel: str
    delivered: bool
    created_at: Optional[str] = None


class SLODashboardResponse(BaseModel):
    target_pct: float
    window_days: int
    rolling_availability_pct: float
    total_probes: int
    successful_probes: int
    failed_probes: int
    services: Dict[str, Dict[str, Any]]
    alert_active: bool
    alert_message: Optional[str] = None
    recent_alerts: List[AvailabilityAlertItem] = Field(default_factory=list)
    daily_uptime: List[SLODailyPoint] = Field(default_factory=list)


class HealthProbeRequest(BaseModel):
    service_name: str = Field(..., description="Service under probe (vigilrag-backend | vigilrag-agent)")
    is_healthy: bool = True
    latency_ms: Optional[int] = None
    detail: Optional[str] = None


class HealthProbeResponse(BaseModel):
    id: str
    service_name: str
    is_healthy: bool
    probed_at: str


class SLOAlertEvaluateResponse(BaseModel):
    breached: bool
    rolling_availability_pct: float
    target_pct: float
    alert_id: Optional[str] = None
    message: Optional[str] = None


