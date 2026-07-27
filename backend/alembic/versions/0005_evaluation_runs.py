"""evaluation_runs table migration for US-021.

Revision ID: 0005_evaluation_runs
Revises: 0004_rbac_foundation
Create Date: 2026-07-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0005_evaluation_runs'
down_revision: Union[str, None] = '0004_rbac_foundation'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'evaluation_runs',
        sa.Column('id', sa.String(length=100), nullable=False),
        sa.Column('pipeline_version', sa.String(length=100), nullable=False),
        sa.Column('dataset_version', sa.String(length=50), nullable=False, server_default='v1.0'),
        sa.Column('total_cases', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('faithfulness', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('context_precision', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('context_recall', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('answer_relevancy', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('passed_threshold', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('run_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('details_json', sa.Text(), nullable=False, server_default='[]'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('evaluation_runs')
