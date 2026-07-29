"""
Feedback Routing Service for US-020 (FEAT-09).

Scans unprocessed negative user feedback and stages items into the FeedbackReviewItem admin queue.
"""

import logging
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import FeedbackRecord, FeedbackReviewItem

logger = logging.getLogger(__name__)


async def route_negative_feedback(session: AsyncSession) -> int:
    """
    Scans negative FeedbackRecord entries and creates pending FeedbackReviewItem records.
    Returns the number of newly created review items.
    """
    fb_stmt = select(FeedbackRecord).where(FeedbackRecord.rating == "negative")
    fb_res = await session.execute(fb_stmt)
    negative_feedbacks = fb_res.scalars().all()

    created_count = 0
    for fb in negative_feedbacks:
        # Check if already routed (by feedback_id or query_id)
        rev_stmt = select(FeedbackReviewItem).where(
            (FeedbackReviewItem.feedback_id == fb.id) | (FeedbackReviewItem.query_id == fb.query_id)
        )
        rev_res = await session.execute(rev_stmt)
        existing_item = rev_res.scalar_one_or_none()

        if not existing_item:
            review_item = FeedbackReviewItem(
                id=f"fbr-{uuid.uuid4().hex[:12]}",
                feedback_id=fb.id,
                query_id=fb.query_id,
                status="pending",
            )
            session.add(review_item)
            created_count += 1

    if created_count > 0:
        await session.commit()
        logger.info(f"Routed {created_count} negative feedback entries to FeedbackReview queue.")

    return created_count
