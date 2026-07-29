"""Alembic migration: compliance-grade audit retention/export tables (US-039).

Revision ID: 0009_audit_compliance
Revises: 0008_service_api_keys
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_audit_compliance"
down_revision: Union[str, None] = "0008_service_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_queries_created_at", "queries", ["created_at"])
    # Postgres FTS GIN index; skipped silently on SQLite via IF NOT EXISTS style not portable —
    # create with raw SQL only when dialect supports it.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_queries_text_fts "
            "ON queries USING GIN (to_tsvector('english', query_text))"
        )

    op.create_table(
        "archived_queries",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("requester_identity", sa.String(length=255), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.String(length=100), nullable=False),
        sa.Column("original_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("groundedness_score", sa.Float(), nullable=True),
        sa.Column("guardrail_flags_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("retention_run_id", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_archived_queries_requester_identity", "archived_queries", ["requester_identity"])
    op.create_index("ix_archived_queries_retention_run_id", "archived_queries", ["retention_run_id"])

    op.create_table(
        "retention_runs",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("records_archived", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit_exports",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("from_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("download_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("identity_filter", sa.String(length=255), nullable=True),
        sa.Column("search_query", sa.String(length=500), nullable=True),
        sa.Column("async_mode", sa.Boolean(), nullable=False),
        sa.Column("notification_sent", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_exports_requested_by", "audit_exports", ["requested_by"])

    op.create_table(
        "scheduled_reports",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("cadence", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("destination", sa.String(length=500), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("scheduled_reports")
    op.drop_index("ix_audit_exports_requested_by", table_name="audit_exports")
    op.drop_table("audit_exports")
    op.drop_table("retention_runs")
    op.drop_index("ix_archived_queries_retention_run_id", table_name="archived_queries")
    op.drop_index("ix_archived_queries_requester_identity", table_name="archived_queries")
    op.drop_table("archived_queries")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_queries_text_fts")
    op.drop_index("idx_queries_created_at", table_name="queries")
