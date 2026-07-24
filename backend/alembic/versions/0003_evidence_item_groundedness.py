"""EvidenceItem, Query, and Answer tables migration for US-013.

Revision ID: 0003_evidence_item_groundedness
Revises: 0002_permission_cache
Create Date: 2026-07-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003_evidence_item_groundedness'
down_revision: Union[str, None] = '0002_permission_cache'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create queries table
    op.create_table(
        'queries',
        sa.Column('id', sa.String(length=100), nullable=False),
        sa.Column('requester_identity', sa.String(length=255), nullable=False),
        sa.Column('query_text', sa.Text(), nullable=False),
        sa.Column('trace_id', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_queries_requester_identity', 'queries', ['requester_identity'])
    op.create_index('idx_queries_trace_id', 'queries', ['trace_id'])

    # 2. Create evidence_items table
    op.create_table(
        'evidence_items',
        sa.Column('id', sa.String(length=100), nullable=False),
        sa.Column('query_id', sa.String(length=100), nullable=False),
        sa.Column('chunk_id', sa.String(length=100), nullable=False),
        sa.Column('source_id', sa.String(length=100), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('relevance_score', sa.Float(), nullable=False),
        sa.Column('rerank_score', sa.Float(), nullable=True),
        sa.Column('used_in_answer', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['query_id'], ['queries.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_evidence_items_query_id', 'evidence_items', ['query_id'])
    op.create_index('idx_evidence_items_chunk_id', 'evidence_items', ['chunk_id'])

    # 3. Create answers table
    op.create_table(
        'answers',
        sa.Column('id', sa.String(length=100), nullable=False),
        sa.Column('query_id', sa.String(length=100), nullable=False),
        sa.Column('answer_text', sa.Text(), nullable=False),
        sa.Column('groundedness_score', sa.Float(), nullable=True),
        sa.Column('guardrail_flags_json', sa.Text(), nullable=False),
        sa.Column('trace_id', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['query_id'], ['queries.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_answers_query_id', 'answers', ['query_id'])
    op.create_index('idx_answers_trace_id', 'answers', ['trace_id'])


def downgrade() -> None:
    op.drop_index('idx_answers_trace_id', table_name='answers')
    op.drop_index('idx_answers_query_id', table_name='answers')
    op.drop_table('answers')
    op.drop_index('idx_evidence_items_chunk_id', table_name='evidence_items')
    op.drop_index('idx_evidence_items_query_id', table_name='evidence_items')
    op.drop_table('evidence_items')
    op.drop_index('idx_queries_trace_id', table_name='queries')
    op.drop_index('idx_queries_requester_identity', table_name='queries')
    op.drop_table('queries')
