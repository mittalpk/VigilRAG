#!/usr/bin/env python3
"""
CLI entry point to execute feedback routing job (US-020).
"""

import asyncio
import logging
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.models import AsyncSessionLocal
from backend.app.services.feedback_routing_service import route_negative_feedback

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting automated feedback routing job...")
    async with AsyncSessionLocal() as session:
        count = await route_negative_feedback(session)
        logger.info(f"Feedback routing job completed. {count} items queued for admin review.")


if __name__ == "__main__":
    asyncio.run(main())
