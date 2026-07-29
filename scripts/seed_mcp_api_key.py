"""
Seed / issue an MCP service API key for agent consumers (US-037).

Usage:
  PYTHONPATH=. python scripts/seed_mcp_api_key.py --username mcp-coding-assistant --name "Claude Desktop"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("INTERNAL_API_KEY", "secure-test-internal-api-key-9999")
os.environ.setdefault("SECRET_KEY", "secure-test-secret-key-9999-jwt")
os.environ.setdefault("ADMIN_PASSWORD", "secure-test-admin-password-9999")


async def main(username: str, key_name: str, role: str) -> None:
    from backend.app.models import AsyncSessionLocal, init_db
    from backend.app.services.mcp_auth_service import issue_service_api_key

    await init_db()
    async with AsyncSessionLocal() as session:
        raw_key, record = await issue_service_api_key(
            session,
            username=username,
            key_name=key_name,
            role_id=role,
            created_by="seed_mcp_api_key",
        )
        await session.commit()

    print("MCP API key issued (store securely — shown once):")
    print(f"  key_id:   {record.id}")
    print(f"  username: {username}")
    print(f"  name:     {key_name}")
    print(f"  role:     {role}")
    print(f"  api_key:  {raw_key}")
    print()
    print("Example:")
    print(f'  curl -H "X-API-Key: {raw_key}" http://localhost:8000/mcp/v1/tools')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Issue a VigilRAG MCP service API key")
    parser.add_argument("--username", default="mcp-service-agent", help="Service identity username")
    parser.add_argument("--name", default="default-mcp-key", help="Human-readable key name")
    parser.add_argument("--role", default="user", choices=["admin", "user", "viewer"])
    args = parser.parse_args()
    asyncio.run(main(args.username, args.name, args.role))
