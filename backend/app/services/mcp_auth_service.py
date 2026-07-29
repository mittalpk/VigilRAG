"""
MCP API-key authentication & service-identity mapping (US-037 / FR-010 / NFR-002).

X-API-Key → SHA-256 hash lookup in ``service_api_keys`` → active service User.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import ServiceApiKey, User, UserRole

logger = logging.getLogger(__name__)

API_KEY_PREFIX = "vr_mcp_"


def hash_api_key(raw_key: str) -> str:
    """Return hex SHA-256 digest of the raw API key (never store plaintext)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    """Generate a high-entropy MCP API key with a recognizable prefix."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


@dataclass
class McpServiceIdentity:
    """Authenticated MCP consumer identity derived from an API key."""

    user_id: str
    username: str
    roles: list[str]
    api_key_id: str
    key_name: str


async def authenticate_api_key(session: AsyncSession, raw_key: Optional[str]) -> McpServiceIdentity:
    """
    Validate ``X-API-Key`` and return the mapped service identity.

    Raises ValueError with a safe public message on failure (mapped to 401 by router).
    """
    if not raw_key or not str(raw_key).strip():
        raise ValueError("Missing X-API-Key header")

    key_hash = hash_api_key(raw_key.strip())
    stmt = select(ServiceApiKey).where(ServiceApiKey.key_hash == key_hash)
    res = await session.execute(stmt)
    record = res.scalar_one_or_none()

    if record is None:
        raise ValueError("Invalid API key")

    if not record.is_active:
        raise ValueError("API key revoked")

    user_stmt = select(User).where(User.id == record.user_id)
    user_res = await session.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    if user is None or not user.is_active:
        raise ValueError("Service identity inactive")

    roles_stmt = select(UserRole.role_id).where(UserRole.user_id == user.id)
    roles_res = await session.execute(roles_stmt)
    roles = [r for r in roles_res.scalars().all()]
    if not roles:
        roles = ["viewer"]

    # Touch last_used_at (best-effort)
    record.last_used_at = datetime.now(timezone.utc)

    return McpServiceIdentity(
        user_id=user.id,
        username=user.username,
        roles=roles,
        api_key_id=record.id,
        key_name=record.name,
    )


async def issue_service_api_key(
    session: AsyncSession,
    *,
    username: str,
    key_name: str,
    role_id: str = "user",
    created_by: str = "system",
) -> tuple[str, ServiceApiKey]:
    """
    Ensure a service User exists, assign role, and issue a new API key.

    Returns (raw_api_key, ServiceApiKey). The raw key is shown once to the caller.
    """
    # Ensure role row exists (tests / fresh DBs)
    from backend.app.models import Role

    role_res = await session.execute(select(Role).where(Role.id == role_id))
    if role_res.scalar_one_or_none() is None:
        session.add(Role(id=role_id, name=role_id, description=f"{role_id} role"))
        await session.flush()

    user_res = await session.execute(select(User).where(User.username == username))
    user = user_res.scalar_one_or_none()
    if user is None:
        user = User(
            id=f"svc-{uuid.uuid4().hex[:12]}",
            username=username,
            hashed_password=f"mcp-service-no-password-{uuid.uuid4().hex}",
            is_active=True,
        )
        session.add(user)
        await session.flush()

    ur_res = await session.execute(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role_id)
    )
    if ur_res.scalar_one_or_none() is None:
        session.add(
            UserRole(
                id=f"ur-{uuid.uuid4().hex[:12]}",
                user_id=user.id,
                role_id=role_id,
                assigned_by=created_by,
            )
        )

    raw_key = generate_api_key()
    record = ServiceApiKey(
        id=f"sak-{uuid.uuid4().hex[:12]}",
        name=key_name,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:12],
        user_id=user.id,
        is_active=True,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
    )
    session.add(record)
    await session.flush()
    logger.info(f"Issued MCP API key '{key_name}' for service identity '{username}'")
    return raw_key, record


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
