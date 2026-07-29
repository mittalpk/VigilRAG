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


class HybridRetrievalResponse(BaseModel):
    evidence: List[EvidenceItem]
    trace_id: str
    execution_time_ms: int
    query: str
    total_retrieved: int


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
