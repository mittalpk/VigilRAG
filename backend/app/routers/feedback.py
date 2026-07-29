"""
Thumbs Up / Down Feedback Router for US-019 (FEAT-09).

Provides:
- POST /api/v1/feedback: Submits quality rating (positive/negative) and optional comment for a query.
"""

import logging
import re
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.auth import get_current_user
from backend.app.models import FeedbackRecord, QueryRecord, get_db_session
from backend.app.schemas import FeedbackCreateRequest, FeedbackResponse

router = APIRouter()
logger = logging.getLogger(__name__)

EMAIL_PII_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}")


@router.post("", response_model=FeedbackResponse)
@router.post("/", response_model=FeedbackResponse)
async def submit_feedback(
    body: FeedbackCreateRequest = Body(...),
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Submits thumbs up/down quality feedback for a query.
    Enforces one feedback submission per (query_id, requester_identity) pair (409 Conflict).
    """
    requester_identity = current_user.get("sub", "user@example.com")

    # Validate rating value
    rating_clean = body.rating.strip().lower()
    if rating_clean not in ("positive", "negative"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Rating must be 'positive' or 'negative'",
        )

    # Basic PII regex check on comment
    if body.comment:
        if EMAIL_PII_REGEX.search(body.comment):
            logger.warning(
                f"PII warning: Feedback comment from requester '{requester_identity}' appears to contain an email address."
            )

    # 1. Verify target query_id exists
    q_stmt = select(QueryRecord).where(QueryRecord.id == body.query_id)
    q_res = await session.execute(q_stmt)
    q_rec = q_res.scalar_one_or_none()

    if not q_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query ID '{body.query_id}' not found",
        )

    # 2. Check for duplicate feedback submission
    fb_stmt = select(FeedbackRecord).where(
        FeedbackRecord.query_id == body.query_id,
        FeedbackRecord.requester_identity == requester_identity,
    )
    fb_res = await session.execute(fb_stmt)
    existing_fb = fb_res.scalar_one_or_none()

    if existing_fb:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feedback already submitted for this query.",
        )

    # 3. Create & persist FeedbackRecord
    feedback_id = f"fbk-{uuid.uuid4().hex[:12]}"
    new_fb = FeedbackRecord(
        id=feedback_id,
        query_id=body.query_id,
        requester_identity=requester_identity,
        rating=rating_clean,
        comment=body.comment.strip() if body.comment else None,
    )
    session.add(new_fb)
    await session.commit()

    return FeedbackResponse(
        received=True,
        feedback_id=feedback_id,
        query_id=body.query_id,
        rating=rating_clean,
        message="Feedback saved successfully",
    )
