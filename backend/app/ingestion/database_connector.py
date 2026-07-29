"""
Structured Database Source Connector for Postgres & Relational Schemas (US-032 / FEAT-12).

Provides:
- DatabaseConnector: Connects to a target relational database (or inspects SQLAlchemy metadata),
  extracts table schemas, column definitions, data types, constraints, and comments.
- Generates structured table representations as Graph-Ready Chunk entities.
- Ingests schema chunks into the database backing hybrid retrieval.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Chunk, Source
from backend.app.services.ingestion_utils import compute_checksum, generate_embedding_vector

logger = logging.getLogger(__name__)


@dataclass
class ColumnMeta:
    name: str
    data_type: str
    is_nullable: bool = True
    default: Optional[str] = None
    comment: Optional[str] = None


@dataclass
class TableMeta:
    table_name: str
    schema_name: str = "public"
    columns: List[ColumnMeta] = field(default_factory=list)
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[Dict[str, str]] = field(default_factory=list)
    table_comment: Optional[str] = None


class DatabaseConnector:
    """Introspects database schemas and ingests table metadata as searchable Chunk records."""

    def __init__(self, source_id: str = "src-db-001", permissions_ref: str = "public"):
        self.source_id = source_id
        self.permissions_ref = permissions_ref

    async def introspect_schema_from_session(
        self,
        session: AsyncSession,
        schema_name: str = "public",
    ) -> List[TableMeta]:
        """Introspects relational database tables and columns using standard information_schema queries."""
        tables_map: Dict[str, TableMeta] = {}

        try:
            # 1. Query tables and columns from information_schema
            query = text("""
                SELECT
                    t.table_name,
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default
                FROM information_schema.tables t
                JOIN information_schema.columns c
                    ON t.table_name = c.table_name AND t.table_schema = c.table_schema
                WHERE t.table_schema = :schema
                  AND t.table_type = 'BASE TABLE'
                ORDER BY t.table_name, c.ordinal_position;
            """)
            res = await session.execute(query, {"schema": schema_name})
            rows = res.fetchall()

            for row in rows:
                tbl_name, col_name, data_type, nullable_str, col_def = row[0], row[1], row[2], row[3], row[4]
                if tbl_name not in tables_map:
                    tables_map[tbl_name] = TableMeta(table_name=tbl_name, schema_name=schema_name)

                col = ColumnMeta(
                    name=col_name,
                    data_type=data_type,
                    is_nullable=(str(nullable_str).upper() == "YES"),
                    default=str(col_def) if col_def else None,
                )
                tables_map[tbl_name].columns.append(col)

        except Exception as exc:
            logger.warning(f"Error querying information_schema ({exc}); fallback to empty schema list.")
            return []

        return list(tables_map.values())

    def format_table_as_chunk_text(self, table: TableMeta) -> str:
        """Formats table schema and column definitions into a clear structured text block for indexing."""
        lines = [
            f"Database Table Schema: {table.table_name} (Schema: {table.schema_name})",
            f"Type: Relational Database Table",
        ]
        if table.table_comment:
            lines.append(f"Description: {table.table_comment}")

        if table.primary_keys:
            lines.append(f"Primary Keys: {', '.join(table.primary_keys)}")

        if table.foreign_keys:
            fk_strs = [f"{fk.get('column')} -> {fk.get('target')}" for fk in table.foreign_keys]
            lines.append(f"Foreign Keys: {', '.join(fk_strs)}")

        lines.append("\nColumns:")
        # Truncate to first 100 columns if table is excessively large (edge case handling)
        cols_to_render = table.columns[:100]
        for col in cols_to_render:
            null_str = "NULL" if col.is_nullable else "NOT NULL"
            default_str = f" DEFAULT {col.default}" if col.default else ""
            comment_str = f" -- {col.comment}" if col.comment else ""
            lines.append(f"  - {col.name} ({col.data_type}, {null_str}{default_str}){comment_str}")

        if len(table.columns) > 100:
            lines.append(f"  ... ({len(table.columns) - 100} additional columns truncated)")

        return "\n".join(lines)

    async def ingest_tables(
        self,
        session: AsyncSession,
        tables: List[TableMeta],
    ) -> List[Chunk]:
        """Ingests table schemas into the chunks table with embeddings and Graph-Ready metadata."""
        ingested_chunks: List[Chunk] = []
        now = datetime.now(timezone.utc)

        for table in tables:
            chunk_id = f"chk-db-{table.schema_name}-{table.table_name}"
            content = self.format_table_as_chunk_text(table)
            checksum = compute_checksum(content)
            vector = generate_embedding_vector(content)

            # References to parent schema doc
            parent_doc_id = f"doc-schema-{table.schema_name}"
            references = [fk.get("target_table") for fk in table.foreign_keys if fk.get("target_table")]

            # Check if chunk exists
            existing_res = await session.execute(select(Chunk).where(Chunk.id == chunk_id))
            existing_chunk = existing_res.scalar_one_or_none()

            if existing_chunk:
                existing_chunk.content = content
                existing_chunk.checksum = checksum
                existing_chunk.embedding_vector_str = json.dumps(vector)
                existing_chunk.permissions_ref = self.permissions_ref
                existing_chunk.last_indexed_at = now
                ingested_chunks.append(existing_chunk)
            else:
                new_chunk = Chunk(
                    id=chunk_id,
                    source_id=self.source_id,
                    document_id=f"doc-tbl-{table.table_name}",
                    parent_doc_id=parent_doc_id,
                    content=content,
                    permissions_ref=self.permissions_ref,
                    checksum=checksum,
                    references_json=json.dumps(references),
                    embedding_vector_str=json.dumps(vector),
                    last_indexed_at=now,
                )
                session.add(new_chunk)
                ingested_chunks.append(new_chunk)

        await session.commit()
        logger.info(f"Ingested {len(ingested_chunks)} database schema chunks into database for source '{self.source_id}'.")
        return ingested_chunks
