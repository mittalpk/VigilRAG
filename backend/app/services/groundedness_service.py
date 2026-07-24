"""
Groundedness Score & Evidence Persistence Service for US-013 (FR-003, FR-008, NFR-004, NFR-007).

Provides:
- calculate_groundedness_and_used_chunks: Computes used_in_answer flag and groundedness_score ratio.
- persist_query_evidence_answer: Async fire-and-forget DB persistence for Query, EvidenceItem, and Answer records.
"""

from datetime import datetime, timezone
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import AnswerRecord, EvidenceItemRecord, QueryRecord

logger = logging.getLogger(__name__)


def calculate_groundedness_and_used_chunks(
    evidence_items: List[Dict[str, Any]],
    answer_text: str,
) -> Tuple[Optional[float], List[Dict[str, Any]]]:
    """
    Computes used_in_answer boolean flag for each evidence item and calculates groundedness_score.
    Returns (groundedness_score, updated_evidence_items).
    """
    if not evidence_items:
        return None, []

    if not answer_text or not str(answer_text).strip():
        # Answer is empty -> 0 used chunks
        updated = []
        for item in evidence_items:
            item_copy = dict(item)
            item_copy["used_in_answer"] = False
            updated.append(item_copy)
        return 0.0, updated

    answer_lower = answer_text.lower()
    answer_words = set(re.findall(r"\w+", answer_lower))

    updated_items = []
    used_count = 0

    for item in evidence_items:
        item_copy = dict(item)
        content = (item.get("content") or item.get("content_excerpt") or "").lower()

        is_used = False
        if content:
            # Substring heuristic: 30-char excerpt match OR significant word intersection
            chunk_excerpt = content[:60].strip()
            if chunk_excerpt and chunk_excerpt in answer_lower:
                is_used = True
            else:
                chunk_words = set(re.findall(r"\w+", content))
                intersection = chunk_words.intersection(answer_words)
                # If significant chunk content words (>= 3 words or >= 30% of chunk) overlap with answer
                if len(intersection) >= 3 or (len(chunk_words) > 0 and len(intersection) / float(len(chunk_words)) >= 0.3):
                    is_used = True

        item_copy["used_in_answer"] = is_used
        if is_used:
            used_count += 1
        updated_items.append(item_copy)

    groundedness_score = float(used_count) / float(len(evidence_items))
    return groundedness_score, updated_items


async def persist_query_evidence_answer(
    session: AsyncSession,
    query_id: str,
    requester_identity: str,
    query_text: str,
    trace_id: str,
    evidence_items: List[Dict[str, Any]],
    answer_text: str,
    guardrail_flags: Optional[List[str]] = None,
) -> bool:
    """
    Persists QueryRecord, EvidenceItemRecord[], and AnswerRecord in a single transaction.
    Fail-safe: Catches persistence errors and logs with trace_id without throwing exception.
    """
    if not query_id:
        query_id = f"qry-{uuid.uuid4().hex[:12]}"
    if not trace_id:
        trace_id = f"trc-{uuid.uuid4().hex[:12]}"

    guardrail_flags = guardrail_flags or []
    groundedness_score, processed_items = calculate_groundedness_and_used_chunks(evidence_items, answer_text)

    try:
        now = datetime.now(timezone.utc)

        # 1. QueryRecord
        q_record = QueryRecord(
            id=query_id,
            requester_identity=requester_identity,
            query_text=query_text,
            trace_id=trace_id,
            created_at=now,
        )
        session.add(q_record)

        # 2. EvidenceItemRecord per chunk
        for item in processed_items:
            ev_record = EvidenceItemRecord(
                id=f"ev-{uuid.uuid4().hex[:12]}",
                query_id=query_id,
                chunk_id=item.get("chunk_id", f"chk-{uuid.uuid4().hex[:8]}"),
                source_id=item.get("source_id", "unknown"),
                source_url=item.get("source_url"),
                relevance_score=float(item.get("relevance_score", 0.0)),
                rerank_score=float(item["rerank_score"]) if item.get("rerank_score") is not None else None,
                used_in_answer=bool(item.get("used_in_answer", False)),
                created_at=now,
            )
            session.add(ev_record)

        # 3. AnswerRecord
        ans_record = AnswerRecord(
            id=f"ans-{uuid.uuid4().hex[:12]}",
            query_id=query_id,
            answer_text=answer_text,
            groundedness_score=groundedness_score,
            guardrail_flags_json=json.dumps(guardrail_flags),
            trace_id=trace_id,
            created_at=now,
        )
        session.add(ans_record)

        await session.commit()
        logger.info(f"Persisted Query ({query_id}), {len(processed_items)} EvidenceItems, and Answer with groundedness {groundedness_score} [trace_id={trace_id}]")
        return True
    except Exception as exc:
        logger.error(f"Failed to persist query evidence audit records for trace_id={trace_id}: {exc}")
        await session.rollback()
        return False
