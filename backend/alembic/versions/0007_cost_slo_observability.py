"""Alembic migration: query_costs, health_probes, availability_alerts (US-036).

Revision ID: 0007_cost_slo_observability
Revises: 0006_feedback_tables
Create Date: 2026-07-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_cost_slo_observability"
down_revision: Union[str, None] = "0006_feedback_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "query_costs",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("query_id", sa.String(length=100), nullable=False),
        sa.Column("trace_id", sa.String(length=100), nullable=False),
        sa.Column("llm_model", sa.String(length=100), nullable=False),
        sa.Column("model_family", sa.String(length=50), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_query_costs_query_id", "query_costs", ["query_id"])
    op.create_index("ix_query_costs_trace_id", "query_costs", ["trace_id"])
    op.create_index("idx_query_costs_created_at", "query_costs", ["created_at"])
    op.create_index("idx_query_costs_model_family", "query_costs", ["model_family"])

    op.create_table(
        "health_probes",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("service_name", sa.String(length=100), nullable=False),
        sa.Column("is_healthy", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("probed_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_probes_service_name", "health_probes", ["service_name"])
    op.create_index("idx_health_probes_probed_at", "health_probes", ["probed_at"])

    op.create_table(
        "availability_alerts",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("alert_type", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("rolling_availability_pct", sa.Float(), nullable=False),
        sa.Column("target_pct", sa.Float(), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("delivered", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("availability_alerts")
    op.drop_index("idx_health_probes_probed_at", table_name="health_probes")
    op.drop_index("ix_health_probes_service_name", table_name="health_probes")
    op.drop_table("health_probes")
    op.drop_index("idx_query_costs_model_family", table_name="query_costs")
    op.drop_index("idx_query_costs_created_at", table_name="query_costs")
    op.drop_index("ix_query_costs_trace_id", table_name="query_costs")
    op.drop_index("ix_query_costs_query_id", table_name="query_costs")
    op.drop_table("query_costs")
