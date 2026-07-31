"""
Model Cards Router.

Provides:
- GET /api/v1/admin/model-cards/latest: Returns the content of the latest published Model/System Card.
- GET /api/v1/admin/model-cards/{version}: Returns the card for a specific pipeline version.
"""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse

from backend.app.auth import require_role

router = APIRouter()

_require_admin = require_role(["admin"])


def _resolve_cards_dir() -> Path:
    """Locate published cards across local, Docker, and test layouts."""
    env = os.environ.get("MODEL_CARDS_DIR")
    if env:
        return Path(env).resolve()

    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "knowledge" / "model-cards",  # .../VigilRAG/knowledge/model-cards (repo)
        here.parents[2] / "knowledge" / "model-cards",  # .../backend/knowledge/model-cards
        Path("/app/knowledge/model-cards"),
        Path.cwd() / "knowledge" / "model-cards",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


CARDS_DIR = _resolve_cards_dir()


def _read_card(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read model card: {exc}") from exc


@router.get("/model-cards/latest", response_class=PlainTextResponse)
async def get_latest_model_card(_admin: None = Depends(_require_admin)):
    """Returns the raw Markdown content of the most recently published Model/System Card."""
    cards_dir = _resolve_cards_dir()
    latest_file = cards_dir / "latest-card.md"
    if not latest_file.is_file():
        # Fall back to newest versioned card if latest symlink/file is missing
        versioned = sorted(cards_dir.glob("v*-card.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if versioned:
            return _read_card(versioned[0])
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No model card has been published for this environment yet.",
        )
    return _read_card(latest_file)


@router.get("/model-cards/{version}", response_class=PlainTextResponse)
async def get_model_card_by_version(version: str, _admin: None = Depends(_require_admin)):
    """Returns the Model/System Card for a specific pipeline version (git SHA)."""
    cards_dir = _resolve_cards_dir()
    clean_ver = version[1:] if version.startswith("v") else version
    target_file = cards_dir / f"v{clean_ver[:8]}-card.md"

    if not target_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model card for version '{version}' was not found.",
        )
    return _read_card(target_file)
