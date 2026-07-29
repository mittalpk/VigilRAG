"""Alembic migration: service_api_keys for MCP gateway (US-037).

Revision ID: 0008_service_api_keys
Revises: 0007_cost_slo_observability
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_service_api_keys"
down_revision: Union[str, None] = "0007_cost_slo_observability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_api_keys",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_service_api_keys_key_hash", "service_api_keys", ["key_hash"])
    op.create_index("ix_service_api_keys_user_id", "service_api_keys", ["user_id"])
    op.create_index("idx_service_api_keys_user_id", "service_api_keys", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_service_api_keys_user_id", table_name="service_api_keys")
    op.drop_index("ix_service_api_keys_user_id", table_name="service_api_keys")
    op.drop_index("ix_service_api_keys_key_hash", table_name="service_api_keys")
    op.drop_table("service_api_keys")
