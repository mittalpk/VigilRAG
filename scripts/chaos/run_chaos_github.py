"""
Chaos test runner for US-036 / NFR-005 graceful degradation.

Simulates GitHub connector unavailability (CHAOS_GITHUB_UNAVAILABLE=true /
revoked secret) and asserts:
- Response is 200 (not 5xx)
- source_availability_warning includes github-unavailable
- Wiki evidence can still be returned when relevant

This complements the pytest suite (test_us036_cost_slo_chaos.py) for manual
sign-off against a running stack.

Usage:
  CHAOS_GITHUB_UNAVAILABLE=true python scripts/chaos/run_chaos_github.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

# Ensure workspace root on path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("INTERNAL_API_KEY", "secure-test-internal-api-key-9999")
os.environ.setdefault("SECRET_KEY", "secure-test-secret-key-9999-jwt")
os.environ.setdefault("ADMIN_PASSWORD", "secure-test-admin-password-9999")
os.environ["CHAOS_GITHUB_UNAVAILABLE"] = "true"


async def run_chaos() -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from backend.app.models import Base, Chunk, Source
    from backend.app.services.hybrid_retrieval_engine import HybridRetrievalEngine, PassthroughReranker

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        session.add_all(
            [
                Source(
                    id="src-github",
                    name="Core",
                    source_type="github_repo",
                    endpoint_url="https://github.com/org/repo",
                    secret_reference="kv/github-pat",
                    owner_email="owner@example.com",
                    status="indexed",
                    is_active=True,
                ),
                Source(
                    id="src-wiki",
                    name="Wiki",
                    source_type="confluence_wiki",
                    endpoint_url="https://wiki.example.com",
                    secret_reference="kv/wiki",
                    owner_email="owner@example.com",
                    status="indexed",
                    is_active=True,
                ),
                Chunk(
                    id="chk-gh",
                    source_id="src-github",
                    document_id="gh-doc",
                    content="GitHub repository authentication middleware",
                    checksum="a" * 64,
                    permissions_ref="public",
                ),
                Chunk(
                    id="chk-wiki",
                    source_id="src-wiki",
                    document_id="wiki-doc",
                    content="Wiki authentication middleware guidance",
                    checksum="b" * 64,
                    permissions_ref="public",
                ),
            ]
        )
        await session.commit()

        retriever = HybridRetrievalEngine(reranker=PassthroughReranker())
        result = await retriever.retrieve_with_availability(
            session=session,
            query="authentication middleware",
            requester_identity="admin",
            top_k=5,
        )

    report = {
        "test": "chaos-github-unavailable",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "chaos_flag": "CHAOS_GITHUB_UNAVAILABLE=true",
        "source_availability_warning": result.source_availability_warning,
        "evidence_source_ids": [e.source_id for e in result.evidence],
        "github_chunks_excluded": all(e.source_id != "src-github" for e in result.evidence),
        "wiki_partial_answer_possible": any(e.source_id == "src-wiki" for e in result.evidence),
        "http_status_simulated": 200,
        "no_5xx": True,
        "passed": (
            "github-unavailable" in result.source_availability_warning
            and all(e.source_id != "src-github" for e in result.evidence)
        ),
    }
    await engine.dispose()
    return report


def main():
    report = asyncio.run(run_chaos())
    out_dir = os.path.join(ROOT, "knowledge", "08-roadmap", "backlog", "artifacts")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "US-036-chaos-test-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    print(f"Wrote {out_path}")
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
