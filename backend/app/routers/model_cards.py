"""
Model Cards Router for US-034 (FR-013 / NFR-012).

Provides:
- GET /api/v1/admin/model-cards/latest: Returns the content of the latest published Model/System Card.
- GET /api/v1/admin/model-cards/{version}: Returns the card for a specific pipeline version.
"""

import os
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse

from backend.app.auth import require_role

router = APIRouter()

# Admin-only dependency enforcement
_require_admin = require_role(["admin"])

CARDS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../knowledge/model-cards"))


@router.get("/model-cards/latest", response_class=PlainTextResponse)
async def get_latest_model_card(_admin: None = Depends(_require_admin)):
    """Returns the raw Markdown content of the most recently published Model/System Card."""
    latest_file = os.path.join(CARDS_DIR, "latest-card.md")
    if not os.path.exists(latest_file):
        raise HTTPException(
            status_code=status.HTTP_444_NOT_FOUND if hasattr(status, "HTTP_444_NOT_FOUND") else 404,
            detail="No Model/System Card has been published yet.",
        )

    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read model card: {exc}")


@router.get("/model-cards/{version}", response_class=PlainTextResponse)
async def get_model_card_by_version(version: str, _admin: None = Depends(_require_admin)):
    """Returns the Model/System Card for a specific pipeline version (git SHA)."""
    clean_ver = version[1:] if version.startswith("v") else version
    target_filename = f"v{clean_ver[:8]}-card.md"
    target_file = os.path.join(CARDS_DIR, target_filename)

    if not os.path.exists(target_file):
        raise HTTPException(
            status_code=404,
            detail=f"Model card for version '{version}' not found.",
        )

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read model card: {exc}")
