"""
Agent-side US-036 tests: source_availability_warning propagation & partial answers.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

# Secure env before app import
os.environ.setdefault("INTERNAL_API_KEY", "secure-test-internal-api-key-9999")
os.environ.setdefault("SECRET_KEY", "secure-test-secret-key-9999-jwt")
os.environ.setdefault("ADMIN_PASSWORD", "secure-test-admin-password-9999")
os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
os.environ["GOOGLE_API_KEY"] = "fake-gemini-key"

from agent.app.main import app
from agent.app.schemas import AgentQueryResponse


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _mock_httpx_response(status_code: int, payload: dict):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


@pytest.mark.asyncio
async def test_agent_propagates_github_unavailable_warning(client):
    kb_payload = {
        "evidence": [
            {
                "chunk_id": "chk-wiki-1",
                "content": "Wiki policy for auth tokens",
                "source_url": "https://wiki/auth",
                "source_id": "src-wiki",
                "source_type": "confluence_wiki",
                "relevance_score": 0.9,
            }
        ],
        "source_availability_warning": ["github-unavailable"],
        "trace_id": "trc-test",
        "query_id": "qry-test",
        "execution_time_ms": 10,
        "query": "auth tokens",
        "total_retrieved": 1,
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_httpx_response(200, kb_payload))

    with patch("agent.app.routers.query.http_client.get_client", return_value=mock_client):
        with patch("agent.app.routers.query.guardrails_client") as gc:
            gc.validate = AsyncMock(return_value=("auth tokens", []))
            scan = MagicMock()
            scan.guardrail_flags = []
            scan.all_flagged = False
            scan.safe_chunks = kb_payload["evidence"]
            gc.scan_evidence.return_value = scan
            redaction = MagicMock()
            redaction.redacted_text = "Based on retrieved evidence partial wiki answer"
            redaction.guardrail_flags = []
            gc.pii_redact.return_value = redaction
            validation = MagicMock()
            validation.valid = True
            gc.validate_output.return_value = validation

            resp = client.post(
                "/api/v1/query",
                headers={"X-Internal-API-Key": os.environ["INTERNAL_API_KEY"]},
                json={"query": "auth tokens", "requester_identity": "user@example.com", "top_k": 5},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "github-unavailable" in data["source_availability_warning"]
    assert "Partial answer" in data["answer"] or "wiki" in data["answer"].lower() or len(data["citations"]) >= 1
    AgentQueryResponse.model_validate(data)


@pytest.mark.asyncio
async def test_agent_both_sources_unavailable_no_hallucination(client):
    kb_payload = {
        "evidence": [],
        "source_availability_warning": ["github-unavailable", "wiki-unavailable"],
        "trace_id": "trc-empty",
        "query_id": "qry-empty",
        "execution_time_ms": 5,
        "query": "anything",
        "total_retrieved": 0,
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_httpx_response(200, kb_payload))

    with patch("agent.app.routers.query.http_client.get_client", return_value=mock_client):
        with patch("agent.app.routers.query.guardrails_client") as gc:
            gc.validate = AsyncMock(return_value=("anything", []))
            scan = MagicMock()
            scan.guardrail_flags = []
            scan.all_flagged = False
            scan.safe_chunks = []
            gc.scan_evidence.return_value = scan
            redaction = MagicMock()
            redaction.redacted_text = (
                "No relevant evidence was found from any available source "
                "(unavailable: github-unavailable, wiki-unavailable). "
                "I cannot provide an answer without evidence."
            )
            redaction.guardrail_flags = []
            gc.pii_redact.side_effect = lambda text, trace_id=None: MagicMock(
                redacted_text=text, guardrail_flags=[]
            )
            validation = MagicMock()
            validation.valid = True
            gc.validate_output.return_value = validation

            resp = client.post(
                "/api/v1/query",
                headers={"X-Internal-API-Key": os.environ["INTERNAL_API_KEY"]},
                json={"query": "anything", "requester_identity": "user@example.com"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert "github-unavailable" in body["source_availability_warning"]
    assert "cannot provide an answer" in body["answer"].lower() or "no relevant evidence" in body["answer"].lower()


def test_agent_query_unauthorized_without_key(client):
    resp = client.post(
        "/api/v1/query",
        json={"query": "x", "requester_identity": "u"},
    )
    assert resp.status_code in (401, 422)


def test_agent_query_missing_requester_identity(client):
    resp = client.post(
        "/api/v1/query",
        headers={"X-Internal-API-Key": os.environ["INTERNAL_API_KEY"]},
        json={"query": "x", "requester_identity": ""},
    )
    assert resp.status_code == 401
