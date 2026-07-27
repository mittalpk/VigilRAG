"""
Unit & Integration Tests for US-021 (RAGAS Evaluation Setup & Golden Dataset Bootstrap).

Tests:
- RAGASEvaluationRunner execution & EvaluationRun persistence.
- Edge cases: missing expected_answer, empty retrieval, threshold passing/failing.
- Modular heuristic metric computation logic.
- CLI runner script integration test (mocked).
"""

import json
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.models import Base, EvaluationCase, EvaluationRun, Source
from backend.app.services.github_connector import GitHubIngestionConnector
from backend.app.services.ragas_evaluator import (
    CaseEvaluationResult,
    RAGASEvaluationRunner,
    compute_heuristics,
    get_git_commit_hash,
)
from backend.app.services.retrieval_evaluator import seed_golden_dataset
from backend.app.services.wiki_connector import WikiIngestionConnector


@pytest_asyncio.fixture
async def async_eval_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def test_compute_heuristics_metrics():
    query = "How are JWT tokens decoded in API?"
    golden_answer = "JWT tokens are decoded using HS256 algorithm and validated against secret_key."
    retrieved_contexts = [
        "JWT tokens are decoded using HS256 algorithm and validated against secret_key."
    ]
    synth = "Based on evidence: JWT tokens are decoded using HS256 algorithm and validated against secret_key."

    faithfulness, ctx_prec, ctx_rec, ans_rel = compute_heuristics(
        query=query,
        golden_answer=golden_answer,
        retrieved_contexts=retrieved_contexts,
        synthesized_answer=synth,
    )

    assert faithfulness >= 0.8
    assert ctx_prec >= 0.5
    assert ctx_rec >= 0.8
    assert ans_rel >= 0.5


def test_compute_heuristics_empty_context():
    faithfulness, ctx_prec, ctx_rec, ans_rel = compute_heuristics(
        query="Any query",
        golden_answer="Any answer",
        retrieved_contexts=[],
        synthesized_answer="No context",
    )
    assert faithfulness == 0.0
    assert ctx_prec == 0.0
    assert ctx_rec == 0.0
    assert ans_rel == 0.0


@pytest.mark.asyncio
async def test_ragas_evaluator_empty_db(async_eval_session: AsyncSession):
    runner = RAGASEvaluationRunner()
    report = await runner.run_evaluation(async_eval_session, threshold_faithfulness=0.85)
    assert report.total_cases == 0
    assert report.faithfulness == 0.0
    assert report.passed_threshold is False


@pytest.mark.asyncio
async def test_ragas_evaluator_single_case_success(async_eval_session: AsyncSession):
    # Seed Source and Chunk
    src = Source(
        id="src-eval-test",
        name="test-repo",
        source_type="github_repo",
        endpoint_url="https://api.github.com/repos/org/test-repo",
        secret_reference="sec-test",
        owner_email="test@org.com",
    )
    async_eval_session.add(src)
    await async_eval_session.commit()

    connector = GitHubIngestionConnector()
    await connector.run_ingestion(
        async_eval_session,
        src,
        mock_files=[
            {"path": "auth.py", "content": "JWT tokens are decoded using HS256 algorithm and validated against secret_key."}
        ]
    )

    from sqlalchemy import update
    from backend.app.models import Chunk
    await async_eval_session.execute(update(Chunk).values(permissions_ref='{"visibility": "public", "allowed_identities": ["*"]}'))
    await async_eval_session.commit()

    # Seed EvaluationCase
    cases_data = [
        {
            "id": "eval-test-01",
            "query": "How are JWT tokens decoded?",
            "expected_answer": "JWT tokens are decoded using HS256 algorithm and validated against secret_key.",
            "expected_chunk_ids": [],
            "source_type": "github_repo",
            "tags": ["auth"],
        }
    ]
    await seed_golden_dataset(async_eval_session, cases_data)

    runner = RAGASEvaluationRunner()
    report = await runner.run_evaluation(async_eval_session, threshold_faithfulness=0.80)

    assert report.total_cases == 1
    assert report.faithfulness >= 0.80
    assert report.passed_threshold is True
    assert report.pipeline_version is not None

    # Verify database persistence of EvaluationRun
    run_db = await async_eval_session.get(EvaluationRun, report.run_id)
    assert run_db is not None
    assert run_db.faithfulness == report.faithfulness
    assert run_db.passed_threshold is True


@pytest.mark.asyncio
async def test_ragas_evaluator_edge_case_missing_answer_skipped(async_eval_session: AsyncSession):
    # Add case with empty expected answer
    bad_case = EvaluationCase(
        id="eval-bad-01",
        query="Query with no expected answer",
        expected_answer="",
        expected_chunk_ids_json="[]",
        source_type="github_repo",
    )
    async_eval_session.add(bad_case)
    await async_eval_session.commit()

    runner = RAGASEvaluationRunner()
    report = await runner.run_evaluation(async_eval_session)
    assert report.total_cases == 0


def test_get_git_commit_hash():
    commit_hash = get_git_commit_hash()
    assert isinstance(commit_hash, str)
    assert len(commit_hash) > 0
