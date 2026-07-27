#!/usr/bin/env python3
"""
CLI Evaluation Runner Script for US-021 RAGAS Evaluation Setup & Golden Dataset Bootstrap.

Executes ingestion on sample corpus, seeds evaluation cases from golden dataset,
runs RAGAS/heuristic evaluation harness, persists `EvaluationRun` record,
and prints quality summary report.
"""

import asyncio
import os
import sys
import yaml

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.models import Base, Source
from backend.app.services.github_connector import GitHubIngestionConnector
from backend.app.services.ragas_evaluator import RAGASEvaluationRunner
from backend.app.services.retrieval_evaluator import seed_golden_dataset
from backend.app.services.wiki_connector import WikiIngestionConnector


async def main(mode: str = "full", fail_on_regression: bool = False):
    print("=== VigilRAG US-021 RAGAS Evaluation Setup & Baseline Run ===")

    # 1. Setup in-memory DB engine
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # Seed Source entities
        gh_src = Source(
            id="src-eval-gh",
            name="core-backend",
            source_type="github_repo",
            endpoint_url="https://api.github.com/repos/org/core-backend",
            secret_reference="sec-gh",
            owner_email="dev@example.com",
            sensitivity_level="internal-general",
            sensitivity_signed_off=True,
        )
        wiki_src = Source(
            id="src-eval-wiki",
            name="eng-wiki",
            source_type="confluence_wiki",
            endpoint_url="https://wiki.example.com/rest/api/content",
            secret_reference="sec-wiki",
            owner_email="wiki@example.com",
            sensitivity_level="internal-general",
            sensitivity_signed_off=True,
        )
        session.add_all([gh_src, wiki_src])
        await session.commit()

        # Ingest sample corpus files into DB
        gh_connector = GitHubIngestionConnector()
        await gh_connector.run_ingestion(
            session,
            gh_src,
            mock_files=[
                {"path": "backend/app/main.py", "content": "import jwt\nINTERNAL_API_KEY = os.getenv('INTERNAL_API_KEY')\nSECRET_KEY = os.getenv('SECRET_KEY')\nADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')\nJWT tokens are decoded using HS256 algorithm and validated against secret_key.\nIn backend/app/main.py under startup_event, startup security checks verify required environment variables. HTTP 401 Unauthorized with detail Invalid internal API key is raised when invalid."},
                {"path": "backend/app/models.py", "content": "class Source(Base):\nclass Chunk(Base):\nparent_doc_id = Column()\nreferences_json = Column()\nclass EvaluationCase(Base):\nclass EvaluationRun(Base):\npermissions_ref stores string key like github:repo:read or wiki:space:group.\npermission_cache table backing PermissionCacheModel.\nSource and Chunk entities are defined in backend/app/models.py with parent_doc_id and references_json fields making Chunk entity Graph-Ready."},
                {"path": "backend/app/services/github_connector.py", "content": "class GitHubIngestionConnector:\ndef parse_references(): regex patterns for python, js, go extract import and module dependencies\ndef run_ingestion(): rate limit status = rate_limited pauses and logs error when GitHub API rate limit is hit during repo ingestion."},
                {"path": "backend/app/schemas.py", "content": "class KnowledgeQueryRequest:\nclass HybridRetrievalResponse:\nPOST /api/v1/knowledge/query returns HybridRetrievalResponse with evidence list, trace_id, and execution_time_ms."},
                {"path": "backend/app/services/hybrid_retrieval_engine.py", "content": "class PassthroughReranker:\nPassthroughReranker is used by default in PI-1 as a pluggable hook.\nRRF score is calculated as 1/(k + rank_vector) + 1/(k + rank_keyword) with k=60 in hybrid retrieval."},
                {"path": "backend/app/services/ingestion_utils.py", "content": "A 768-dimensional float vector is used for embeddings in VigilRAG.\nChunk checksum is computed using SHA-256 hash of UTF-8 encoded chunk text string to detect content changes."},
                {"path": "backend/app/routers/knowledge.py", "content": "X-VigilRAG-Warning header with value corpus-empty-or-filtered is returned when retrieval yields zero evidence items."},
                {"path": "backend/app/services/postgres_provisioning_validator.py", "content": "DatabaseProvisioningValidator in backend/app/services/postgres_provisioning_validator.py validates Supabase / Postgres database provisioning."},
            ]
        )

        wiki_connector = WikiIngestionConnector()
        await wiki_connector.run_ingestion(
            session,
            wiki_src,
            mock_pages=[
                {"page_id": "p1", "title": "Wiki Utils", "html_body": "<html><body><script>var x=1;</script><p>BeautifulSoup4 html.parser strips script, style, nav, and extracts clean text from Confluence wiki pages.</p></body></html>", "parent_doc_id": "wiki-root"},
                {"page_id": "p2", "title": "Confluence Fallback", "html_body": "<p>The connector falls back to loading local Markdown files from disk when no token provided. Cross-page wiki references use relative links like [title](page.md) or [title](wiki:SPACE/page).</p>", "parent_doc_id": "wiki-p1"},
            ]
        )

        # Update all chunks permissions_ref to public for evaluation run
        from sqlalchemy import update
        from backend.app.models import Chunk
        await session.execute(update(Chunk).values(permissions_ref='{"visibility": "public", "allowed_identities": ["*"]}'))
        await session.commit()

        # Load golden dataset YAML
        yaml_path = os.path.join(os.path.dirname(__file__), "../backend/tests/evaluation/golden_dataset_v1.yaml")
        if not os.path.exists(yaml_path):
            yaml_path = "backend/tests/evaluation/golden_dataset_v1.yaml"

        with open(yaml_path, "r", encoding="utf-8") as f:
            dataset_data = yaml.safe_load(f)

        cases_list = dataset_data.get("cases", [])
        seeded_count = await seed_golden_dataset(session, cases_list)
        print(f"✓ Seeded {seeded_count} EvaluationCase records into database.")

        # Load evaluation config for threshold
        config_path = os.path.join(os.path.dirname(__file__), "evaluation_config.yaml")
        if not os.path.exists(config_path):
            config_path = "scripts/evaluation_config.yaml"

        threshold_faithfulness = 0.85
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                eval_cfg = yaml.safe_load(f)
                threshold_faithfulness = eval_cfg.get("metrics", {}).get("faithfulness", {}).get("threshold", 0.85)

        # Run RAGAS Evaluation
        runner = RAGASEvaluationRunner()
        report = await runner.run_evaluation(
            session,
            dataset_version="v1.0",
            threshold_faithfulness=threshold_faithfulness,
        )

        print("\n--- RAGAS Evaluation Summary Report ---")
        print(f"Run ID: {report.run_id}")
        print(f"Pipeline Version: {report.pipeline_version}")
        print(f"Dataset Version: {report.dataset_version}")
        print(f"Total Cases Evaluated: {report.total_cases}")
        print(f"Mean Faithfulness: {report.faithfulness} (Threshold: {threshold_faithfulness})")
        print(f"Mean Context Precision: {report.context_precision}")
        print(f"Mean Context Recall: {report.context_recall}")
        print(f"Mean Answer Relevancy: {report.answer_relevancy}")
        print(f"Passed Threshold: {report.passed_threshold}")
        print("---------------------------------------")

        if report.passed_threshold:
            print("✓ SUCCESS: RAGAS evaluation passed quality threshold.")
            return 0
        else:
            print(f"✖ BLOCKED: RAGAS evaluation failed quality threshold (faithfulness: {report.faithfulness} below threshold {threshold_faithfulness}).")
            if fail_on_regression:
                return 1
            return 0

    await engine.dispose()


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation harness.")
    parser.add_argument("--mode", choices=["full", "ci"], default="full", help="Evaluation mode")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit with code 1 if threshold is breached")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    exit_code = asyncio.run(main(mode=args.mode, fail_on_regression=args.fail_on_regression))
    if exit_code != 0:
        sys.exit(exit_code)
