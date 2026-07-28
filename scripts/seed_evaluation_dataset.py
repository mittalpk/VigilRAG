#!/usr/bin/env python3
"""
CLI Evaluation Dataset Seeder Script for US-023.

Loads golden dataset evaluation cases from golden_dataset_v1.yaml
and seeds them into the database session. Supports --mode ci for fast-CI subsets.
"""

import argparse
import asyncio
import os
import sys
import yaml

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.models import Base
from backend.app.services.retrieval_evaluator import seed_golden_dataset


async def seed_dataset(limit: int = 0):
    yaml_path = os.path.join(os.path.dirname(__file__), "../backend/tests/evaluation/golden_dataset_v1.yaml")
    if not os.path.exists(yaml_path):
        yaml_path = "backend/tests/evaluation/golden_dataset_v1.yaml"

    if not os.path.exists(yaml_path):
        print(f"✖ ERROR: Golden dataset file not found at {yaml_path}")
        sys.exit(1)

    with open(yaml_path, "r", encoding="utf-8") as f:
        dataset_data = yaml.safe_load(f)

    cases_list = dataset_data.get("cases", [])
    if limit > 0:
        cases_list = cases_list[:limit]

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        seeded_count = await seed_golden_dataset(session, cases_list)
        print(f"✓ Successfully seeded {seeded_count} EvaluationCase records.")

    await engine.dispose()
    return seeded_count


def main():
    parser = argparse.ArgumentParser(description="Seed EvaluationCase dataset.")
    parser.add_argument("--mode", choices=["full", "ci"], default="full", help="Seeding mode: full or fast-CI subset")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of cases to seed")
    args = parser.parse_args()

    limit = args.limit
    if args.mode == "ci" and limit == 0:
        limit = 10

    asyncio.run(seed_dataset(limit=limit))


if __name__ == "__main__":
    main()
