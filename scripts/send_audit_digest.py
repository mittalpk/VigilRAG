#!/usr/bin/env python3
"""
CLI entry point to send compliance audit digests (US-039 / FEAT-08).

Weekly or monthly summary → Compliance Officer via log / Slack / email.
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
from backend.app.services.audit_digest_service import send_audit_digest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main(cadence: str, channel: str | None, destination: str | None) -> int:
    logger.info("Sending audit digest (cadence=%s)...", cadence)
    async with AsyncSessionLocal() as session:
        result = await send_audit_digest(
            session,
            cadence=cadence,
            channel=channel,
            destination=destination,
        )
        await session.commit()
    logger.info("Digest delivery: %s", json.dumps({k: v for k, v in result.items() if k != "markdown"}))
    if result.get("markdown"):
        logger.info("Digest markdown:\n%s", result["markdown"])
    return 0 if result.get("status") == "sent" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send VigilRAG compliance audit digest")
    parser.add_argument("--cadence", choices=("weekly", "monthly"), default="weekly")
    parser.add_argument("--channel", default=None, help="Override AUDIT_DIGEST_CHANNEL (log|slack|email)")
    parser.add_argument("--destination", default=None, help="Webhook URL or email destination")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.cadence, args.channel, args.destination)))
