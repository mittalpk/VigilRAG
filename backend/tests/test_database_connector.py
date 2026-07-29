"""
Unit & Integration Tests for US-032 Database Source Connector.
"""

from datetime import datetime, timezone
import pytest

from backend.app.ingestion.database_connector import (
    ColumnMeta,
    DatabaseConnector,
    TableMeta,
)
from backend.app.models import AsyncSessionLocal, Chunk, Source, init_db


@pytest.fixture
def sample_tables():
    return [
        TableMeta(
            table_name="orders",
            schema_name="public",
            table_comment="Tracks customer orders and total purchase amounts.",
            primary_keys=["id"],
            foreign_keys=[{"column": "customer_id", "target": "customers.id", "target_table": "customers"}],
            columns=[
                ColumnMeta(name="id", data_type="uuid", is_nullable=False, default="gen_random_uuid()"),
                ColumnMeta(name="customer_id", data_type="uuid", is_nullable=False),
                ColumnMeta(name="order_status", data_type="varchar(50)", is_nullable=False, default="'pending'"),
                ColumnMeta(name="total_amount", data_type="numeric(10,2)", is_nullable=False, default="0.00"),
                ColumnMeta(name="created_at", data_type="timestamptz", is_nullable=False),
            ],
        ),
        TableMeta(
            table_name="customers",
            schema_name="public",
            table_comment="Contains customer profile information.",
            primary_keys=["id"],
            columns=[
                ColumnMeta(name="id", data_type="uuid", is_nullable=False),
                ColumnMeta(name="email", data_type="varchar(255)", is_nullable=False),
                ColumnMeta(name="full_name", data_type="varchar(255)", is_nullable=True),
            ],
        ),
    ]


def test_format_table_as_chunk_text(sample_tables):
    connector = DatabaseConnector(source_id="src-db-001")
    text_content = connector.format_table_as_chunk_text(sample_tables[0])

    assert "Database Table Schema: orders" in text_content
    assert "Tracks customer orders" in text_content
    assert "Primary Keys: id" in text_content
    assert "Foreign Keys: customer_id -> customers.id" in text_content
    assert "- customer_id (uuid, NOT NULL)" in text_content
    assert "- total_amount (numeric(10,2), NOT NULL DEFAULT 0.00)" in text_content


@pytest.mark.asyncio
async def test_ingest_database_tables_and_searchability(sample_tables):
    await init_db()

    async with AsyncSessionLocal() as session:
        # Create prerequisite Source record
        source_id = "src-db-test-001"
        src = Source(
            id=source_id,
            name="Test Customer Orders Postgres DB",
            source_type="database_schema",
            endpoint_url="postgresql://db.example.com/production",
            secret_reference="kv-secret-db-prod",
            owner_email="data-eng@example.com",
            sensitivity_level="internal-general",
            sensitivity_signed_off=True,
            refresh_cadence_minutes=1440,
            status="indexed",
            indexing_scope="*",
            is_active=True,
        )
        session.add(src)
        await session.commit()

        # Ingest tables
        connector = DatabaseConnector(source_id=source_id)
        chunks = await connector.ingest_tables(session=session, tables=sample_tables)

        assert len(chunks) == 2
        chunk_ids = [c.id for c in chunks]
        assert "chk-db-public-orders" in chunk_ids
        assert "chk-db-public-customers" in chunk_ids

        # Retrieve and verify database chunk content
        from backend.app.services.hybrid_retrieval_engine import HybridRetrievalEngine
        retriever = HybridRetrievalEngine()

        results = await retriever.retrieve(
            session=session,
            query="what tables track customer orders?",
            requester_identity="user@example.com",
            top_k=5,
        )

        assert len(results) >= 1
        found_order_chunk = any("orders" in r.content.lower() for r in results)
        assert found_order_chunk is True
