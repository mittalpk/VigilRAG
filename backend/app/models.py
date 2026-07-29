"""
Database Session, Engine & Migration Infrastructure (US-005).

Provides async SQLAlchemy engine setup, session management, and table models for:
- Source (registry entity)
- Chunk (vector/semantic entity with Graph-Ready metadata: parent_doc_id, references)
- PermissionCache (permission caching model)
"""

import os
from typing import AsyncGenerator, Dict, List, Optional
from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///:memory:",  # In-memory default fallback for tests
)

# Replace postgresql:// or postgres:// with postgresql+asyncpg:// if postgres URL is passed
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


class Source(Base):
    """Source entity backing FR-007 and Data Architecture §5."""

    __tablename__ = "sources"

    id = Column(String(100), primary_key=True)
    name = Column(String(255), nullable=False)
    source_type = Column(String(50), nullable=False)  # github_repo, confluence_wiki, database_schema
    endpoint_url = Column(Text, nullable=False)
    secret_reference = Column(String(255), nullable=False)
    owner_email = Column(String(255), nullable=False)
    sensitivity_level = Column(String(50), nullable=False, default="internal-general")
    sensitivity_signed_off = Column(Boolean, nullable=False, default=False)
    refresh_cadence_minutes = Column(Integer, nullable=False, default=1440)
    status = Column(String(50), nullable=False, default="pending_first_index")  # pending_first_index, indexing, indexed, error, inactive
    indexing_scope = Column(Text, nullable=True, default="*")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now(), nullable=False)
    last_indexed_at = Column(DateTime(timezone=True), nullable=True)

    chunks = relationship("Chunk", back_populates="source", cascade="all, delete-orphan")



class Chunk(Base):
    """Chunk entity storing vector embeddings and Graph-Ready metadata (parent_doc_id, references)."""

    __tablename__ = "chunks"

    id = Column(String(100), primary_key=True)
    source_id = Column(String(100), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    document_id = Column(String(255), nullable=False)
    parent_doc_id = Column(String(255), nullable=True)  # Graph-Ready: section/parent hierarchy
    content = Column(Text, nullable=False)
    permissions_ref = Column(String(255), nullable=True)

    checksum = Column(String(64), nullable=False)
    
    # Store references as JSON string or comma-separated string for multi-DB compatibility (SQLite + Postgres)
    references_json = Column(Text, nullable=True, default="[]")
    
    # Text field for vector string representation (pgvector vector(1536) in PostgreSQL)
    embedding_vector_str = Column(Text, nullable=True)

    last_indexed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    source = relationship("Source", back_populates="chunks")


    __table_args__ = (
        Index("idx_chunks_source_id", "source_id"),
        Index("idx_chunks_permissions_ref", "permissions_ref"),
        Index("idx_chunks_parent_doc_id", "parent_doc_id"),
    )


class PermissionCacheModel(Base):
    """PermissionCache entity backing FR-006 and ADR-001."""

    __tablename__ = "permission_cache"

    cache_id = Column(String(100), primary_key=True)
    requester_identity = Column(String(255), nullable=False)
    source_id = Column(String(100), nullable=False)
    access_level = Column(String(50), nullable=False, default="read")
    granted_acl_refs_json = Column(Text, nullable=False, default="[]")
    cached_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ttl_seconds = Column(Integer, nullable=False, default=900)

    __table_args__ = (
        Index("idx_perm_cache_identity_source", "requester_identity", "source_id"),
    )


class EvaluationCase(Base):
    """EvaluationCase entity backing US-009, US-021, and Data Architecture §5."""

    __tablename__ = "evaluation_cases"

    id = Column(String(100), primary_key=True)
    query = Column(Text, nullable=False)
    expected_answer = Column(Text, nullable=False)
    expected_chunk_ids_json = Column(Text, nullable=False, default="[]")
    source_type = Column(String(50), nullable=False)  # github_repo, confluence_wiki, cross_source
    tags_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class QueryRecord(Base):
    """Query entity backing US-013, US-018, and Data Architecture §5."""

    __tablename__ = "queries"

    id = Column(String(100), primary_key=True)
    requester_identity = Column(String(255), nullable=False, index=True)
    query_text = Column(Text, nullable=False)
    trace_id = Column(String(100), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EvidenceItemRecord(Base):
    """EvidenceItem entity backing US-013, US-018, and Data Architecture §5."""

    __tablename__ = "evidence_items"

    id = Column(String(100), primary_key=True)
    query_id = Column(String(100), ForeignKey("queries.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String(100), nullable=False, index=True)
    source_id = Column(String(100), nullable=False)
    source_url = Column(Text, nullable=True)
    relevance_score = Column(Float, nullable=False, default=0.0)
    rerank_score = Column(Float, nullable=True)
    used_in_answer = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AnswerRecord(Base):
    """Answer entity backing US-013, US-018, and Data Architecture §5."""

    __tablename__ = "answers"

    id = Column(String(100), primary_key=True)
    query_id = Column(String(100), ForeignKey("queries.id", ondelete="CASCADE"), nullable=False, index=True)
    answer_text = Column(Text, nullable=False)
    groundedness_score = Column(Float, nullable=True)
    guardrail_flags_json = Column(Text, nullable=False, default="[]")
    trace_id = Column(String(100), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    """User entity backing RBAC (US-016) and authentication."""

    __tablename__ = "users"

    id = Column(String(100), primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Role(Base):
    """Role entity backing RBAC foundation (US-016)."""

    __tablename__ = "roles"

    id = Column(String(50), primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)


class UserRole(Base):
    """UserRole association backing RBAC role assignment (US-016)."""

    __tablename__ = "user_roles"

    id = Column(String(100), primary_key=True)
    user_id = Column(String(100), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(String(50), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_by = Column(String(100), nullable=False)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)





class EvaluationRun(Base):
    """EvaluationRun entity backing US-021, US-022, US-023, and Data Architecture §5."""

    __tablename__ = "evaluation_runs"

    id = Column(String(100), primary_key=True)
    pipeline_version = Column(String(100), nullable=False)
    dataset_version = Column(String(50), nullable=False, default="v1.0")
    total_cases = Column(Integer, nullable=False, default=0)
    faithfulness = Column(Float, nullable=False, default=0.0)
    context_precision = Column(Float, nullable=False, default=0.0)
    context_recall = Column(Float, nullable=False, default=0.0)
    answer_relevancy = Column(Float, nullable=False, default=0.0)
    passed_threshold = Column(Boolean, nullable=False, default=True)
    run_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    details_json = Column(Text, nullable=False, default="[]")


class FeedbackRecord(Base):
    """Feedback entity backing US-019, FR-009, and Data Architecture §5."""

    __tablename__ = "feedback"

    id = Column(String(100), primary_key=True)
    query_id = Column(String(100), ForeignKey("queries.id", ondelete="CASCADE"), nullable=False, index=True)
    requester_identity = Column(String(255), nullable=False, index=True)
    rating = Column(String(20), nullable=False)  # 'positive' or 'negative'
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("query_id", "requester_identity", name="uq_feedback_query_identity"),
    )


class FeedbackReviewItem(Base):
    """FeedbackReviewItem entity backing US-020, FR-009, and Data Architecture §5."""

    __tablename__ = "feedback_review_items"

    id = Column(String(100), primary_key=True)
    feedback_id = Column(String(100), ForeignKey("feedback.id", ondelete="CASCADE"), nullable=True, index=True)
    query_id = Column(String(100), ForeignKey("queries.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")  # 'pending', 'promoted', 'dismissed', 'needs_investigation'
    golden_answer = Column(Text, nullable=True)
    reviewed_by = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class QueryCost(Base):
    """Per-query token cost aggregation backing US-036 / NFR-009 cost dashboard."""

    __tablename__ = "query_costs"

    id = Column(String(100), primary_key=True)
    query_id = Column(String(100), nullable=False, index=True)
    trace_id = Column(String(100), nullable=False, index=True)
    llm_model = Column(String(100), nullable=False)
    model_family = Column(String(50), nullable=False, default="Pro")  # Flash | Pro | Other
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_query_costs_created_at", "created_at"),
        Index("idx_query_costs_model_family", "model_family"),
    )


class HealthProbe(Base):
    """Health-probe samples for availability SLO tracking (US-036 / NFR-008)."""

    __tablename__ = "health_probes"

    id = Column(String(100), primary_key=True)
    service_name = Column(String(100), nullable=False, index=True)
    is_healthy = Column(Boolean, nullable=False, default=True)
    latency_ms = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)
    probed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_health_probes_probed_at", "probed_at"),
    )


class AvailabilityAlert(Base):
    """Fired when 30-day rolling availability drops below the SLO target (US-036)."""

    __tablename__ = "availability_alerts"

    id = Column(String(100), primary_key=True)
    alert_type = Column(String(100), nullable=False, default="availability_slo_breach")
    message = Column(Text, nullable=False)
    rolling_availability_pct = Column(Float, nullable=False)
    target_pct = Column(Float, nullable=False, default=99.5)
    channel = Column(String(50), nullable=False, default="log")
    delivered = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


async def init_db():

    """Helper to initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency provider for FastAPI / application database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
