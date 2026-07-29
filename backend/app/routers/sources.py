"""
Source Registration & Self-Service Management Router (US-031 / FR-007).

Provides admin-only endpoints to:
- GET /api/v1/admin/sources/types (supported connector types)
- GET /api/v1/admin/sources (list registered sources)
- POST /api/v1/admin/sources (register a new source, returns 409 if duplicate endpoint_url exists)
- GET /api/v1/admin/sources/{id} (get source detail)
- PATCH /api/v1/admin/sources/{id} (update source configuration)
- POST /api/v1/admin/sources/{id}/trigger-index (trigger ingestion pipeline run)
- DELETE /api/v1/admin/sources/{id} (deactivate source soft-delete)
"""

import asyncio
from datetime import datetime, timezone
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.auth import require_role
from backend.app.models import AsyncSessionLocal, Source
from backend.app.schemas import (
    SourceCreateRequest,
    SourceListResponse,
    SourceResponse,
    SourceTypeInfo,
    SourceUpdateRequest,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Admin role dependency enforcement
_require_admin = require_role(["admin"])

SUPPORTED_SOURCE_TYPES: List[SourceTypeInfo] = [
    SourceTypeInfo(
        type_id="github_repo",
        display_name="GitHub Repository",
        description="Source code, READMEs, and repository Markdown documentation",
        supported=True,
    ),
    SourceTypeInfo(
        type_id="confluence_wiki",
        display_name="Confluence / Wiki Space",
        description="Enterprise wiki documentation, technical specs, and architecture pages",
        supported=True,
    ),
    SourceTypeInfo(
        type_id="wiki_local",
        display_name="Local / Markdown Docs",
        description="Local directory or file-based Markdown knowledge base",
        supported=True,
    ),
    SourceTypeInfo(
        type_id="database_schema",
        display_name="Database / Structured Schema",
        description="Relational database tables, column metadata, and schema definitions (FEAT-12)",
        supported=False,
    ),
]


def _format_source_response(src: Source) -> SourceResponse:
    return SourceResponse(
        id=src.id,
        name=src.name,
        source_type=src.source_type,
        endpoint_url=src.endpoint_url,
        secret_reference=src.secret_reference,
        owner_email=src.owner_email,
        sensitivity_level=src.sensitivity_level,
        sensitivity_signed_off=src.sensitivity_signed_off,
        refresh_cadence_minutes=src.refresh_cadence_minutes,
        status=src.status or "pending_first_index",
        indexing_scope=src.indexing_scope or "*",
        is_active=src.is_active if src.is_active is not None else True,
        created_at=src.created_at.isoformat() if src.created_at else datetime.now(timezone.utc).isoformat(),
        updated_at=src.updated_at.isoformat() if src.updated_at else datetime.now(timezone.utc).isoformat(),
        last_indexed_at=src.last_indexed_at.isoformat() if src.last_indexed_at else None,
    )


@router.get("/sources/types", response_model=List[SourceTypeInfo])
async def list_source_types(_admin: None = Depends(_require_admin)):
    """Returns supported connector types for administrative registration."""
    return SUPPORTED_SOURCE_TYPES


@router.get("/sources", response_model=SourceListResponse)
async def list_sources(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    include_inactive: bool = Query(False),
    _admin: None = Depends(_require_admin),
):
    """Lists registered sources with pagination and status."""
    async with AsyncSessionLocal() as session:
        query = select(Source)
        if not include_inactive:
            query = query.where(Source.is_active.is_(True))

        cnt_stmt = select(func.count()).select_from(query.subquery())
        cnt_res = await session.execute(cnt_stmt)
        total = cnt_res.scalar() or 0

        query = query.order_by(Source.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
        res = await session.execute(query)
        sources = res.scalars().all()

        return SourceListResponse(
            items=[_format_source_response(s) for s in sources],
            total=total,
            page=page,
            size=per_page,
        )


@router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreateRequest = Body(...),
    _admin: None = Depends(_require_admin),
):
    """Registers a new knowledge source. Returns 409 if endpoint_url already exists."""
    async with AsyncSessionLocal() as session:
        # Check duplicate registration by endpoint_url
        dup_stmt = select(Source).where(Source.endpoint_url == payload.endpoint_url, Source.is_active.is_(True))
        dup_res = await session.execute(dup_stmt)
        if dup_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This source is already registered ({payload.endpoint_url}).",
            )

        source_id = f"src-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        new_source = Source(
            id=source_id,
            name=payload.name,
            source_type=payload.source_type,
            endpoint_url=payload.endpoint_url,
            secret_reference=payload.secret_reference,
            owner_email=payload.owner_email,
            sensitivity_level=payload.sensitivity_level,
            sensitivity_signed_off=payload.sensitivity_signed_off,
            refresh_cadence_minutes=payload.refresh_cadence_minutes,
            status="pending_first_index",
            indexing_scope=payload.indexing_scope or "*",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(new_source)
        await session.commit()
        await session.refresh(new_source)

        logger.info(f"Registered new source '{new_source.name}' ({new_source.id})")
        return _format_source_response(new_source)


@router.get("/sources/{source_id}", response_model=SourceResponse)
async def get_source_detail(
    source_id: str,
    _admin: None = Depends(_require_admin),
):
    """Fetches details for a single registered source."""
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Source).where(Source.id == source_id))
        source = res.scalar_one_or_none()
        if not source:
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")
        return _format_source_response(source)


@router.patch("/sources/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: str,
    payload: SourceUpdateRequest = Body(...),
    _admin: None = Depends(_require_admin),
):
    """Updates configuration for a registered source."""
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Source).where(Source.id == source_id))
        source = res.scalar_one_or_none()
        if not source:
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")

        update_data = payload.model_dump(exclude_unset=True)
        for key, val in update_data.items():
            setattr(source, key, val)

        source.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(source)

        logger.info(f"Updated source configuration for '{source_id}'")
        return _format_source_response(source)


@router.post("/sources/{source_id}/trigger-index", response_model=SourceResponse)
async def trigger_source_indexing(
    source_id: str,
    _admin: None = Depends(_require_admin),
):
    """Triggers an ingestion run for the specified source and transitions status pending -> indexing -> indexed."""
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Source).where(Source.id == source_id))
        source = res.scalar_one_or_none()
        if not source:
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")

        if not source.is_active:
            raise HTTPException(status_code=400, detail="Cannot trigger indexing for an inactive source.")

        source.status = "indexing"
        source.updated_at = datetime.now(timezone.utc)
        await session.commit()

        # Simulate async background ingestion task completion
        async def run_ingestion():
            await asyncio.sleep(0.5)
            async with AsyncSessionLocal() as bg_session:
                bg_res = await bg_session.execute(select(Source).where(Source.id == source_id))
                bg_source = bg_res.scalar_one_or_none()
                if bg_source:
                    bg_source.status = "indexed"
                    bg_source.last_indexed_at = datetime.now(timezone.utc)
                    bg_source.updated_at = datetime.now(timezone.utc)
                    await bg_session.commit()
                    logger.info(f"Completed ingestion run for source '{source_id}' -> indexed")

        asyncio.create_task(run_ingestion())
        await session.refresh(source)
        return _format_source_response(source)


@router.delete("/sources/{source_id}", response_model=SourceResponse)
async def deactivate_source(
    source_id: str,
    _admin: None = Depends(_require_admin),
):
    """Deactivates (soft-deletes) a registered source."""
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Source).where(Source.id == source_id))
        source = res.scalar_one_or_none()
        if not source:
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")

        source.is_active = False
        source.status = "inactive"
        source.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(source)

        logger.info(f"Deactivated source '{source_id}'")
        return _format_source_response(source)
