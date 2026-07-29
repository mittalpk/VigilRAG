"""feedback and feedback_review_items tables migration for US-019 and US-020.

Revision ID: 0006_feedback_tables
Revises: 0005_evaluation_runs
Create Date: 2026-07-29

GAP-N04 fix: these tables were missing from the Alembic chain, meaning they
would not be created by `alembic upgrade head` in production. They were only
created via `init_db()` (create_all) in test environments.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0006_feedback_tables'
down_revision: Union[str, None] = '0005_evaluation_runs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # feedback table (US-019)
    op.create_table(
        'feedback',
        sa.Column('id', sa.String(length=100), nullable=False),
        sa.Column('query_id', sa.String(length=100), nullable=False),
        sa.Column('requester_identity', sa.String(length=255), nullable=False),
        sa.Column('rating', sa.String(length=20), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['query_id'], ['queries.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('query_id', 'requester_identity', name='uq_feedback_query_identity'),
    )
    op.create_index('idx_feedback_query_id', 'feedback', ['query_id'])
    op.create_index('idx_feedback_requester_identity', 'feedback', ['requester_identity'])

    # feedback_review_items table (US-020)
    op.create_table(
        'feedback_review_items',
        sa.Column('id', sa.String(length=100), nullable=False),
        sa.Column('feedback_id', sa.String(length=100), nullable=True),
        sa.Column('query_id', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('golden_answer', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['feedback_id'], ['feedback.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['query_id'], ['queries.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_feedback_review_feedback_id', 'feedback_review_items', ['feedback_id'])
    op.create_index('idx_feedback_review_query_id', 'feedback_review_items', ['query_id'])
    op.create_index('idx_feedback_review_status', 'feedback_review_items', ['status'])


def downgrade() -> None:
    op.drop_index('idx_feedback_review_status', table_name='feedback_review_items')
    op.drop_index('idx_feedback_review_query_id', table_name='feedback_review_items')
    op.drop_index('idx_feedback_review_feedback_id', table_name='feedback_review_items')
    op.drop_table('feedback_review_items')

    op.drop_index('idx_feedback_requester_identity', table_name='feedback')
    op.drop_index('idx_feedback_query_id', table_name='feedback')
    op.drop_table('feedback')
