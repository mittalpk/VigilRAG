"""
MCP Agent Tool Gateway (US-037 / FR-010).

Thin protocol adapter exposing VigilRAG's cited query capability as a
standards-based Model Context Protocol tool. Does not duplicate query logic —
proxies to agent ``POST /api/v1/query`` with the authenticated service identity.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.client import http_client
from backend.app.config import settings
from backend.app.models import get_db_session
from backend.app.schemas import (
    McpCitation,
    McpErrorResponse,
    McpQueryResponse,
    McpToolDefinition,
    McpToolInputSchema,
    McpToolInvokeRequest,
    McpToolsManifestResponse,
)
from backend.app.services.mcp_auth_service import McpServiceIdentity, authenticate_api_key
from backend.app.services.mcp_rate_limiter import mcp_rate_limiter
from backend.app.tracing import trace_span

router = APIRouter()
logger = logging.getLogger(__name__)

AGENT_SERVICE_URL = (
    os.environ.get("AGENT_SERVICE_URL")
    or os.environ.get("AGENT_FQDN")
    or "http://ca-vigilrag-agent:8000"
).rstrip("/")

VIGILRAG_QUERY_TOOL = McpToolDefinition(
    name="vigilrag_query",
    description=(
        "Query VigilRAG's enterprise knowledge base with a natural language question. "
        "Returns a cited answer drawn from indexed sources."
    ),
    input_schema=McpToolInputSchema(
        type="object",
        properties={
            "query": {"type": "string", "description": "Natural language question"},
            "top_k": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
                "description": "Number of evidence items to retrieve",
            },
            "requester_identity": {
                "type": "string",
                "description": (
                    "Optional service identity; must match the identity bound to the API key"
                ),
            },
        },
        required=["query"],
    ),
)

# Roles permitted to invoke knowledge queries via MCP (same as human UI)
_MCP_ALLOWED_ROLES = {"admin", "user"}


def _mcp_error(code: str, message: str, http_status: int) -> JSONResponse:
    """MCP-standard error envelope without internal exception details."""
    return JSONResponse(
        status_code=http_status,
        content={"error": {"code": code, "message": message}},
    )


async def require_mcp_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_db_session),
) -> McpServiceIdentity:
    """Authenticate MCP requests via X-API-Key → service identity."""
    # Also accept Authorization: Bearer <api-key> for MCP clients that prefer it
    raw = x_api_key
    if not raw:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            raw = auth[7:].strip()

    try:
        identity = await authenticate_api_key(session, raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    return identity


def _enforce_query_role(identity: McpServiceIdentity) -> None:
    if not any(r in _MCP_ALLOWED_ROLES for r in identity.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Permission denied: service identity '{identity.username}' "
                f"with roles {identity.roles} cannot invoke vigilrag_query"
            ),
        )


@router.get("/tools", response_model=McpToolsManifestResponse)
async def list_mcp_tools(
    identity: McpServiceIdentity = Depends(require_mcp_api_key),
):
    """Publish the MCP tool manifest for discovery by external agents."""
    # Rate-limit discovery separately but share the MCP pool
    rl = mcp_rate_limiter.check(f"discover:{identity.api_key_id}")
    if not rl.allowed:
        return _mcp_error(
            "rate_limited",
            "MCP rate limit exceeded; retry later",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    with trace_span(
        "mcp.list_tools",
        attributes={
            "mcp.tool_name": "list_tools",
            "requester_identity": identity.username,
        },
    ):
        return McpToolsManifestResponse(tools=[VIGILRAG_QUERY_TOOL])


@router.post(
    "/tools/vigilrag_query",
    response_model=McpQueryResponse,
    responses={
        400: {"model": McpErrorResponse},
        401: {"model": McpErrorResponse},
        403: {"model": McpErrorResponse},
        429: {"model": McpErrorResponse},
        502: {"model": McpErrorResponse},
        503: {"model": McpErrorResponse},
        504: {"model": McpErrorResponse},
    },
)
async def invoke_vigilrag_query(
    body: McpToolInvokeRequest = Body(...),
    identity: McpServiceIdentity = Depends(require_mcp_api_key),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Translate an MCP ``vigilrag_query`` invocation into an internal agent query.

    The authenticated service identity is the sole requester_identity used
    downstream — caller-supplied mismatches are rejected with 403.
    """
    gateway_start = time.perf_counter()
    trace_id = x_trace_id or f"trc-mcp-{uuid.uuid4().hex[:12]}"

    # Rate limit (MCP pool)
    rl = mcp_rate_limiter.check(f"invoke:{identity.api_key_id}")
    if not rl.allowed:
        return _mcp_error(
            "rate_limited",
            f"MCP rate limit exceeded ({rl.limit}/window); retry after {rl.retry_after_seconds:.1f}s",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    _enforce_query_role(identity)

    # Identity binding: optional caller-supplied identity must match API key mapping
    if body.requester_identity is not None and str(body.requester_identity).strip():
        supplied = str(body.requester_identity).strip()
        if supplied != identity.username and supplied != identity.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "requester_identity does not match the authenticated API key "
                    "service identity"
                ),
            )

    if not body.query or not str(body.query).strip():
        return _mcp_error(
            "invalid_params",
            "query is required and must be a non-empty string",
            status.HTTP_400_BAD_REQUEST,
        )

    span_attributes = {
        "mcp.tool_name": "vigilrag_query",
        "requester_identity": identity.username,
        "query.length": len(body.query),
        "retrieval.top_k": body.top_k,
    }

    with trace_span("mcp.vigilrag_query", attributes=span_attributes, trace_id=trace_id):
        # Measure pure gateway overhead up to the outbound call
        pre_call_ms = int((time.perf_counter() - gateway_start) * 1000)

        internal_key = settings.internal_api_key.get_secret_value()
        payload = {
            "query": body.query.strip(),
            "requester_identity": identity.username,
            "top_k": body.top_k,
        }
        headers = {
            "X-Internal-API-Key": internal_key,
            "X-Trace-ID": trace_id,
            "Content-Type": "application/json",
        }
        endpoint = f"{AGENT_SERVICE_URL}/api/v1/query"

        client = http_client.get_client()
        try:
            resp = await client.post(endpoint, json=payload, headers=headers, timeout=60.0)
        except httpx.ConnectError as exc:
            logger.error(f"MCP gateway cannot reach agent at {endpoint}: {exc}")
            return _mcp_error(
                "upstream_unavailable",
                "Knowledge query service unavailable",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except httpx.TimeoutException:
            return _mcp_error(
                "upstream_timeout",
                "Knowledge query service timed out",
                status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception as exc:
            logger.error(f"MCP gateway unexpected transport error: {exc}")
            return _mcp_error(
                "internal_error",
                "MCP gateway failed to invoke query tool",
                status.HTTP_502_BAD_GATEWAY,
            )

        if resp.status_code == 401:
            return _mcp_error(
                "upstream_unauthorized",
                "Upstream query service rejected authentication",
                status.HTTP_502_BAD_GATEWAY,
            )
        if resp.status_code == 403:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied by upstream query service",
            )
        if resp.status_code >= 500:
            return _mcp_error(
                "upstream_error",
                "Knowledge query service returned an error",
                status.HTTP_502_BAD_GATEWAY,
            )
        if resp.status_code >= 400:
            # Malformed / validation — do not leak upstream body
            return _mcp_error(
                "invalid_params",
                "Tool invocation rejected by upstream query service",
                status.HTTP_400_BAD_REQUEST,
            )

        try:
            data = resp.json()
        except Exception:
            return _mcp_error(
                "upstream_error",
                "Malformed response from knowledge query service",
                status.HTTP_502_BAD_GATEWAY,
            )

        citations = [
            McpCitation(
                chunk_id=c.get("chunk_id", ""),
                source_url=c.get("source_url", ""),
                source_type=c.get("source_type", "unknown"),
                content_excerpt=c.get("content_excerpt", ""),
            )
            for c in (data.get("citations") or [])
            if isinstance(c, dict)
        ]

        # Gateway overhead = total wall time minus reported agent execution time
        total_ms = int((time.perf_counter() - gateway_start) * 1000)
        agent_ms = int(data.get("execution_time_ms") or 0)
        overhead_ms = max(0, total_ms - agent_ms) if agent_ms > 0 else max(pre_call_ms, 0)

        return McpQueryResponse(
            answer=data.get("answer") or "",
            citations=citations,
            trace_id=data.get("trace_id") or trace_id,
            guardrail_flags=list(data.get("guardrail_flags") or []),
            execution_time_ms=agent_ms or total_ms,
            source_availability_warning=list(data.get("source_availability_warning") or []),
            mcp_gateway_overhead_ms=overhead_ms,
        )
