"""
Agent Service Unified Query API Router for US-011 / US-024 / US-025 / US-026.

Provides:
- POST /api/v1/query: Orchestrates retrieval over backend Knowledge API, applies Guardrails scan,
  synthesises cited answer, runs Presidio PII redaction, and performs answer-out output validation before returning response.
"""

from datetime import datetime
import logging
import os
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
import httpx

from agent.app.client import http_client
from agent.app.config import settings
from agent.app.schemas import AgentQueryRequest, AgentQueryResponse, Citation
from agent.app.guardrails import GuardrailsClient

router = APIRouter(prefix="/api/v1", tags=["query"])
logger = logging.getLogger(__name__)
guardrails_client = GuardrailsClient()


async def verify_internal_key(x_internal_api_key: str = Header(...)):
    """Verifies X-Internal-API-Key header against configured settings."""
    import hmac
    expected_key = settings.internal_api_key.get_secret_value()
    if not hmac.compare_digest(x_internal_api_key, expected_key):
        raise HTTPException(status_code=401, detail="Invalid internal API key")


@router.post("/query", response_model=AgentQueryResponse)
async def execute_agent_query(
    body: AgentQueryRequest = Body(...),
    _: None = Depends(verify_internal_key),
) -> AgentQueryResponse:
    start_time = datetime.now()
    trace_id = f"trc-{uuid.uuid4().hex[:12]}"

    # Validate requester_identity presence
    if not body.requester_identity or not str(body.requester_identity).strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="requester_identity is required",
        )

    # 1. Guardrails query validation
    try:
        sanitized_query, query_flags = await guardrails_client.validate(body.query, trace_id=trace_id)
    except Exception as exc:
        logger.error(f"Guardrails service unavailable during query validation: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Guardrails service unavailable: {exc}",
        )

    guardrail_flags: List[str] = list(query_flags)

    # 2. Call Backend Knowledge API
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
    knowledge_endpoint = f"{backend_url}/api/v1/knowledge/query"

    headers = {
        "X-Internal-API-Key": settings.internal_api_key.get_secret_value(),
        "X-Trace-ID": trace_id,
        "Content-Type": "application/json",
    }
    payload = {
        "query": sanitized_query,
        "requester_identity": body.requester_identity,
        "top_k": body.top_k,
    }

    client = http_client.get_client()
    try:
        response = await client.post(knowledge_endpoint, json=payload, headers=headers, timeout=10.0)
    except Exception as exc:
        logger.error(f"Failed to connect to Knowledge API at {knowledge_endpoint}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Knowledge API backend service unavailable: {exc}",
        )

    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Unauthorized access from backend Knowledge API")

    if response.status_code >= 500:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Knowledge API returned server error: {response.status_code}",
        )

    kb_data = response.json()
    evidence_items = kb_data.get("evidence", [])

    # 3. Guardrails scan over evidence chunks (US-024)
    try:
        scan_res = guardrails_client.scan_evidence(evidence_items, trace_id=trace_id)
    except Exception as exc:
        logger.error(f"Guardrails service unavailable during evidence scanning: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Guardrails service unavailable: {exc}",
        )

    for flag in scan_res.guardrail_flags:
        if flag not in guardrail_flags:
            guardrail_flags.append(flag)

    safe_evidence_items = scan_res.safe_chunks

    # 4. Assemble Citations & Synthesize Answer
    citations: List[Citation] = []

    if scan_res.all_flagged:
        answer = "I could not find reliable information — all retrieved content was flagged by safety guardrails."
    elif len(safe_evidence_items) == 0:
        answer = "The corpus contains no relevant results or access is restricted for your identity."
    else:
        for item in safe_evidence_items:
            chunk_id = item.get("chunk_id", "")
            doc_id = item.get("document_id", "doc-001")
            source_url = item.get("source_url") or f"https://sources.example.com/{doc_id}"
            content = item.get("content", "")
            excerpt = content[:200] if content else ""

            citations.append(
                Citation(
                    chunk_id=chunk_id,
                    source_url=source_url,
                    source_type=item.get("source_type", "github_repo"),
                    content_excerpt=excerpt,
                )
            )

        # LLM Synthesis over evidence
        evidence_summary = "\n---\n".join(
            f"[{c.chunk_id}] {c.content_excerpt}" for c in citations
        )
        answer = f"Based on retrieved evidence:\n{evidence_summary}\n\nConclusion: Processed query '{sanitized_query}' successfully."

    # 5. PII Detection & Redaction (US-026)
    redaction_res = guardrails_client.pii_redact(answer, trace_id=trace_id)
    answer = redaction_res.redacted_text
    for flag in redaction_res.guardrail_flags:
        if flag not in guardrail_flags:
            guardrail_flags.append(flag)

    exec_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

    response_dict = {
        "answer": answer,
        "citations": [c.model_dump() for c in citations],
        "trace_id": trace_id,
        "guardrail_flags": guardrail_flags,
        "execution_time_ms": exec_time_ms,
    }

    # 6. Output Validation Check (US-025 - answer-out guardrail)
    validation = guardrails_client.validate_output(response_dict, trace_id=trace_id)
    if not validation.valid:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Output validation failed: {validation.reason}",
        )

    return AgentQueryResponse.model_validate(response_dict)
