#!/usr/bin/env python3
"""
CLI entry point to enforce audit retention policy (US-039 / NFR-004).

Archives Query+Answer+Evidence older than AUDIT_RETENTION_DAYS into
``archived_queries``, then deletes from hot ``queries`` (CASCADE).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.models import AsyncSessionLocal
from backend.app.services.audit_retention_service import enforce_audit_retention, get_retention_days

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main(retention_days: int | None, batch_size: int) -> int:
    days = retention_days if retention_days is not None else get_retention_days()
    logger.info("Starting audit retention enforcement (days=%s, batch_size=%s)...", days, batch_size)
    async with AsyncSessionLocal() as session:
        result = await enforce_audit_retention(
            session,
            retention_days=days,
            batch_size=batch_size,
        )
        await session.commit()
    logger.info("Retention job finished: %s", json.dumps(result))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enforce VigilRAG audit retention policy")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help=f"Override AUDIT_RETENTION_DAYS (default env={get_retention_days()})",
    )
    parser.add_argument("--batch-size", type=int, default=100, help="Transactional batch size")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.days, args.batch_size)))
