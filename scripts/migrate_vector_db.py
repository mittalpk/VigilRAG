"""
Migrate VigilRAG chunk embeddings to a dedicated vector DB (US-038).

Reads all Chunk records from Postgres, upserts into the target backend
(Qdrant by default), validates counts (abort if mismatch > 0.1%), and
optionally exercises dual-write consistency checks.

Usage:
  PYTHONPATH=. python scripts/migrate_vector_db.py --target qdrant --dry-run
  PYTHONPATH=. python scripts/migrate_vector_db.py --target qdrant
  VECTOR_SEARCH_DUAL_WRITE=true PYTHONPATH=. python scripts/migrate_vector_db.py --validate-only

Rollback: set VECTOR_SEARCH_BACKEND=pgvector (Postgres remains source of truth).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("INTERNAL_API_KEY", "secure-test-internal-api-key-9999")
os.environ.setdefault("SECRET_KEY", "secure-test-secret-key-9999-jwt")
os.environ.setdefault("ADMIN_PASSWORD", "secure-test-admin-password-9999")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_vector_db")


async def migrate(target: str, dry_run: bool, validate_only: bool) -> dict:
    from sqlalchemy import select

    from backend.app.models import AsyncSessionLocal, Chunk, init_db
    from backend.app.services.vector_graduation_service import validate_migration_counts
    from backend.app.services.vector_search.pgvector_backend import PgvectorBackend
    from backend.app.services.vector_search.qdrant_backend import QdrantVectorSearchBackend
    from backend.app.services.vector_search.dual_write import DualWriteVectorSearchBackend

    await init_db()
    report = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "dry_run": dry_run,
        "validate_only": validate_only,
        "upserted": 0,
        "skipped_no_embedding": 0,
        "source_count": 0,
        "target_count": 0,
        "validation": None,
        "passed": False,
    }

    async with AsyncSessionLocal() as session:
        pg = PgvectorBackend(session)
        if target == "qdrant":
            dest = QdrantVectorSearchBackend(
                url=os.getenv("QDRANT_URL", ""),
                collection=os.getenv("QDRANT_COLLECTION", "vigilrag_chunks"),
                api_key=os.getenv("QDRANT_API_KEY") or None,
                allow_memory_fallback=True,
            )
        else:
            raise SystemExit(f"Unsupported target '{target}' (supported: qdrant)")

        res = await session.execute(select(Chunk).where(Chunk.deleted_at.is_(None)))
        chunks = list(res.scalars().all())
        report["source_count"] = len([c for c in chunks if c.embedding_vector_str])

        if validate_only:
            report["target_count"] = await dest.count()
            report["validation"] = await validate_migration_counts(
                report["source_count"], report["target_count"]
            )
            report["passed"] = bool(report["validation"]["ok"])
            return report

        for chk in chunks:
            if not chk.embedding_vector_str:
                report["skipped_no_embedding"] += 1
                continue
            try:
                embedding = json.loads(chk.embedding_vector_str)
            except Exception:
                report["skipped_no_embedding"] += 1
                continue

            if dry_run:
                report["upserted"] += 1
                continue

            await dest.upsert(
                chk.id,
                embedding,
                payload={
                    "chunk_id": chk.id,
                    "source_id": chk.source_id,
                    "document_id": chk.document_id,
                    "permissions_ref": chk.permissions_ref,
                },
            )
            report["upserted"] += 1

        report["target_count"] = await dest.count() if not dry_run else report["upserted"]
        report["validation"] = await validate_migration_counts(
            report["source_count"], report["target_count"]
        )
        report["passed"] = bool(report["validation"]["ok"])

        if report["passed"] and not dry_run:
            logger.info(
                "Migration counts OK. Enable dual-write then cut over:\n"
                "  VECTOR_SEARCH_DUAL_WRITE=true\n"
                "  # after soak:\n"
                "  VECTOR_SEARCH_BACKEND=qdrant VECTOR_SEARCH_DUAL_WRITE=false"
            )
            # Optional consistency sample
            dual = DualWriteVectorSearchBackend(primary=pg, secondary=dest)
            if chunks and chunks[0].embedding_vector_str:
                sample_vec = json.loads(chunks[0].embedding_vector_str)
                consistency = await dual.compare_search_consistency(sample_vec, top_k=5)
                report["consistency_sample"] = consistency

        if not report["passed"]:
            logger.error(
                "ABORT: count mismatch %.4f > 0.1%% — do not cut over",
                report["validation"]["mismatch_ratio"] * 100,
            )

    return report


def main():
    parser = argparse.ArgumentParser(description="Migrate chunk embeddings to a dedicated vector DB")
    parser.add_argument("--target", default="qdrant", choices=["qdrant"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--out",
        default=os.path.join(
            ROOT, "knowledge", "08-roadmap", "backlog", "artifacts", "US-038-migration-run.json"
        ),
    )
    args = parser.parse_args()
    report = asyncio.run(migrate(args.target, args.dry_run, args.validate_only))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    print(f"Wrote {args.out}")
    sys.exit(0 if report["passed"] or args.dry_run else 1)


if __name__ == "__main__":
    main()
