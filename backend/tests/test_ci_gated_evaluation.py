"""
Unit & Integration Tests for US-023 CI-Gated Evaluation Runner & Dataset Seeder.

Tests:
- seed_evaluation_dataset.py script logic (full & fast-CI subset mode).
- run_evaluation.py script CLI options (--mode ci, --fail-on-regression).
- Regression breach exit status code check (exit 1 on failure when --fail-on-regression passed).
"""

import os
import subprocess
import sys
import pytest


def test_seed_evaluation_dataset_ci_mode():
    env = {**os.environ, "PYTHONPATH": "."}
    res = subprocess.run(
        [sys.executable, "scripts/seed_evaluation_dataset.py", "--mode", "ci"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0, f"stdout: {res.stdout}, stderr: {res.stderr}"
    assert "Successfully seeded 10 EvaluationCase records" in res.stdout


def test_run_evaluation_cli_pass():
    env = {**os.environ, "PYTHONPATH": "."}
    res = subprocess.run(
        [sys.executable, "scripts/run_evaluation.py", "--mode", "ci", "--fail-on-regression"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0, f"stdout: {res.stdout}, stderr: {res.stderr}"
    assert "✓ SUCCESS: RAGAS evaluation passed quality threshold" in res.stdout


def test_run_evaluation_cli_fail_on_regression_exit_code():
    # Pass an impossibly high threshold via environment/arg mock to verify exit code 1
    import sys
    from unittest.mock import patch
    from backend.app.services.ragas_evaluator import RAGASEvalRunReport
    from scripts.run_evaluation import main

    with patch("backend.app.services.ragas_evaluator.RAGASEvaluationRunner.run_evaluation") as mock_eval:
        mock_eval.return_value = RAGASEvalRunReport(
            run_id="run-fail",
            pipeline_version="git-test",
            dataset_version="v1.0",
            total_cases=10,
            faithfulness=0.50,
            context_precision=0.50,
            context_recall=0.50,
            answer_relevancy=0.50,
            passed_threshold=False,
            cases=[],
        )

        import asyncio
        exit_code = asyncio.run(main(mode="ci", fail_on_regression=True))
        assert exit_code == 1
