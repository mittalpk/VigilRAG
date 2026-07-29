"""
Minimal generic MCP HTTP client for reference integration tests (US-037).

Uses only stdlib/httpx against published MCP endpoint contracts — no VigilRAG
SDK or VigilRAG-specific client library.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx


class GenericMcpHttpClient:
    """Standards-oriented MCP tool client: discover + invoke via HTTP JSON."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def list_tools(self, client: httpx.Client) -> Dict[str, Any]:
        resp = client.get(
            f"{self.base_url}/mcp/v1/tools",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}

    def call_tool(
        self,
        client: httpx.Client,
        tool_name: str,
        arguments: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers = self._headers()
        if trace_id:
            headers["X-Trace-ID"] = trace_id
        resp = client.post(
            f"{self.base_url}/mcp/v1/tools/{tool_name}",
            headers=headers,
            json=arguments,
            timeout=self.timeout,
        )
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        return {"status_code": resp.status_code, "body": body}
