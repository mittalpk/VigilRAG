"""
Compliance audit export — CSV/PDF with TTL download tokens (US-039 / NFR-002).

Large exports return 202 and complete asynchronously; meta-audit logs every export.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import AnswerRecord, AuditExport, EvidenceItemRecord, QueryRecord

logger = logging.getLogger(__name__)


def get_export_ttl_seconds() -> int:
    return max(60, int(os.getenv("AUDIT_EXPORT_TTL_SECONDS", "3600")))


def get_async_threshold() -> int:
    return max(1, int(os.getenv("AUDIT_EXPORT_ASYNC_THRESHOLD", "10000")))


def get_export_dir() -> Path:
    path = Path(os.getenv("AUDIT_EXPORT_DIR", "./data/audit_exports"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_dt(value: str) -> datetime:
    raw = value.strip()
    if len(raw) == 10:
        raw = f"{raw}T00:00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _load_export_rows(
    session: AsyncSession,
    *,
    from_dt: datetime,
    to_dt: datetime,
    identity: Optional[str] = None,
    q: Optional[str] = None,
) -> List[Dict[str, Any]]:
    stmt = select(QueryRecord).where(
        QueryRecord.created_at >= from_dt,
        QueryRecord.created_at <= to_dt,
    )
    if identity and identity.strip():
        stmt = stmt.where(QueryRecord.requester_identity.ilike(f"%{identity.strip()}%"))
    if q and q.strip():
        term = q.strip()
        # SQLite-compatible FTS fallback; Postgres can use to_tsvector via dialect-specific path
        stmt = stmt.where(QueryRecord.query_text.ilike(f"%{term}%"))

    stmt = stmt.order_by(QueryRecord.created_at.asc())
    res = await session.execute(stmt)
    queries = list(res.scalars().all())

    rows: List[Dict[str, Any]] = []
    for qr in queries:
        ans_res = await session.execute(
            select(AnswerRecord).where(AnswerRecord.query_id == qr.id).limit(1)
        )
        ans = ans_res.scalar_one_or_none()
        ev_res = await session.execute(
            select(EvidenceItemRecord).where(EvidenceItemRecord.query_id == qr.id)
        )
        evidence = list(ev_res.scalars().all())
        flags = []
        if ans and ans.guardrail_flags_json:
            try:
                flags = json.loads(ans.guardrail_flags_json)
            except Exception:
                flags = []
        rows.append(
            {
                "query_id": qr.id,
                "requester_identity": qr.requester_identity,
                "query_text": qr.query_text,
                "trace_id": qr.trace_id,
                "timestamp": qr.created_at.isoformat() if qr.created_at else "",
                "answer_text": ans.answer_text if ans else "",
                "groundedness_score": ans.groundedness_score if ans else None,
                "guardrail_flags": flags,
                "evidence_count": len(evidence),
                "evidence": [
                    {
                        "chunk_id": e.chunk_id,
                        "source_id": e.source_id,
                        "source_url": e.source_url,
                        "relevance_score": e.relevance_score,
                        "used_in_answer": e.used_in_answer,
                    }
                    for e in evidence
                ],
            }
        )
    return rows


def _render_csv(rows: List[Dict[str, Any]]) -> bytes:
    buf = StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "query_id",
            "requester_identity",
            "timestamp",
            "query_text",
            "answer_text",
            "groundedness_score",
            "guardrail_flags",
            "evidence_count",
            "trace_id",
        ],
    )
    writer.writeheader()
    for r in rows:
        writer.writerow(
            {
                "query_id": r["query_id"],
                "requester_identity": r["requester_identity"],
                "timestamp": r["timestamp"],
                "query_text": r["query_text"],
                "answer_text": r["answer_text"],
                "groundedness_score": r["groundedness_score"],
                "guardrail_flags": "|".join(r["guardrail_flags"] or []),
                "evidence_count": r["evidence_count"],
                "trace_id": r["trace_id"],
            }
        )
    return buf.getvalue().encode("utf-8")


def _render_json(rows: List[Dict[str, Any]]) -> bytes:
    return json.dumps({"queries": rows, "count": len(rows)}, indent=2).encode("utf-8")


def _render_pdf(rows: List[Dict[str, Any]]) -> bytes:
    """Generate a simple multi-page PDF (one query per page) via reportlab."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch
    except ImportError as exc:
        raise RuntimeError("reportlab is required for PDF audit exports") from exc

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="VigilRAG Audit Export")
    styles = getSampleStyleSheet()
    story = []

    if not rows:
        story.append(Paragraph("No audit records in the selected date range.", styles["Normal"]))
    else:
        for idx, r in enumerate(rows):
            story.append(Paragraph(f"Query {idx + 1}: {r['query_id']}", styles["Heading2"]))
            story.append(Paragraph(f"<b>Identity:</b> {r['requester_identity']}", styles["Normal"]))
            story.append(Paragraph(f"<b>Timestamp:</b> {r['timestamp']}", styles["Normal"]))
            story.append(Paragraph(f"<b>Trace:</b> {r['trace_id']}", styles["Normal"]))
            story.append(Spacer(1, 0.15 * inch))
            story.append(Paragraph(f"<b>Query:</b> {_pdf_escape(r['query_text'])}", styles["Normal"]))
            story.append(Spacer(1, 0.1 * inch))
            story.append(Paragraph(f"<b>Answer:</b> {_pdf_escape(r['answer_text'] or '')}", styles["Normal"]))
            flags = ", ".join(r["guardrail_flags"] or []) or "none"
            story.append(Paragraph(f"<b>Guardrail flags:</b> {flags}", styles["Normal"]))
            story.append(Paragraph(f"<b>Groundedness:</b> {r['groundedness_score']}", styles["Normal"]))
            story.append(Spacer(1, 0.15 * inch))
            ev_rows = [["chunk_id", "source_id", "relevance", "used"]]
            for e in r.get("evidence") or []:
                ev_rows.append(
                    [
                        str(e.get("chunk_id", ""))[:24],
                        str(e.get("source_id", ""))[:20],
                        str(e.get("relevance_score", "")),
                        str(e.get("used_in_answer", "")),
                    ]
                )
            if len(ev_rows) == 1:
                ev_rows.append(["—", "—", "—", "—"])
            table = Table(ev_rows, colWidths=[1.8 * inch, 1.5 * inch, 1.0 * inch, 0.8 * inch])
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            story.append(table)
            if idx < len(rows) - 1:
                from reportlab.platypus import PageBreak

                story.append(PageBreak())

    doc.build(story)
    return buffer.getvalue()


def _pdf_escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


async def log_meta_audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    detail: str,
) -> Optional[str]:
    """Best-effort meta-audit row; never raises to block the primary action."""
    try:
        qid = f"qry-meta-{uuid.uuid4().hex[:10]}"
        session.add(
            QueryRecord(
                id=qid,
                requester_identity=actor,
                query_text=f"AUDIT_META:{action}:{detail}"[:2000],
                trace_id=f"trc-meta-{uuid.uuid4().hex[:10]}",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.flush()
        return qid
    except Exception as exc:
        logger.warning(f"Meta-audit logging failed (non-blocking): {exc}")
        return None


async def create_audit_export(
    session: AsyncSession,
    *,
    requested_by: str,
    from_date: str,
    to_date: str,
    fmt: str = "csv",
    identity: Optional[str] = None,
    q: Optional[str] = None,
    force_async: bool = False,
) -> Dict[str, Any]:
    """Create an export job; sync when under threshold, else async (202 path)."""
    fmt_clean = (fmt or "csv").strip().lower()
    if fmt_clean not in ("csv", "pdf", "json"):
        raise ValueError("format must be csv, pdf, or json")

    from_dt = _parse_dt(from_date)
    to_dt = _parse_dt(to_date)
    if to_dt < from_dt:
        raise ValueError("to_date must be >= from_date")

    # Count first for async decision
    count_stmt = select(func.count()).select_from(QueryRecord).where(
        QueryRecord.created_at >= from_dt,
        QueryRecord.created_at <= to_dt,
    )
    if identity and identity.strip():
        count_stmt = count_stmt.where(QueryRecord.requester_identity.ilike(f"%{identity.strip()}%"))
    if q and q.strip():
        count_stmt = count_stmt.where(QueryRecord.query_text.ilike(f"%{q.strip()}%"))
    cnt_res = await session.execute(count_stmt)
    row_count = int(cnt_res.scalar() or 0)

    raw_token = secrets.token_urlsafe(32)
    export_id = f"aex-{uuid.uuid4().hex[:12]}"
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=get_export_ttl_seconds())
    async_mode = force_async or row_count >= get_async_threshold()

    export = AuditExport(
        id=export_id,
        requested_by=requested_by,
        from_date=from_dt,
        to_date=to_dt,
        format=fmt_clean,
        status="pending",
        row_count=row_count,
        download_token_hash=_hash_token(raw_token),
        expires_at=expires_at,
        identity_filter=identity,
        search_query=q,
        async_mode=async_mode,
        notification_sent=False,
    )
    session.add(export)
    await session.flush()

    await log_meta_audit(
        session,
        actor=requested_by,
        action="export_requested",
        detail=f"export_id={export_id};format={fmt_clean};rows={row_count};async={async_mode}",
    )

    if async_mode:
        # Generate immediately in-process for portability (no worker queue required);
        # caller still receives 202 semantics via status=pending→ready.
        try:
            await _materialize_export(session, export, raw_token)
            export.notification_sent = True
            await session.flush()
            await _notify_export_ready(export)
        except Exception as exc:
            export.status = "failed"
            export.error_message = str(exc)[:2000]
            await session.flush()
            raise

        return {
            "export_id": export_id,
            "status": export.status,
            "async": True,
            "row_count": export.row_count,
            "download_url": f"/api/v1/audit/exports/{export_id}/download?token={raw_token}",
            "expires_at": expires_at.isoformat(),
            "message": "Large export accepted; file generated and notification channel updated.",
        }

    await _materialize_export(session, export, raw_token)
    await log_meta_audit(
        session,
        actor=requested_by,
        action="export_ready",
        detail=f"export_id={export_id};format={fmt_clean};rows={export.row_count}",
    )
    return {
        "export_id": export_id,
        "status": "ready",
        "async": False,
        "row_count": export.row_count,
        "download_url": f"/api/v1/audit/exports/{export_id}/download?token={raw_token}",
        "expires_at": expires_at.isoformat(),
    }


async def _materialize_export(session: AsyncSession, export: AuditExport, raw_token: str) -> None:
    rows = await _load_export_rows(
        session,
        from_dt=export.from_date,
        to_dt=export.to_date,
        identity=export.identity_filter,
        q=export.search_query,
    )
    if export.format == "csv":
        payload = _render_csv(rows)
        suffix = "csv"
    elif export.format == "pdf":
        payload = _render_pdf(rows)
        suffix = "pdf"
    else:
        payload = _render_json(rows)
        suffix = "json"

    out_path = get_export_dir() / f"{export.id}.{suffix}"
    out_path.write_bytes(payload)
    export.file_path = str(out_path)
    export.row_count = len(rows)
    export.status = "ready"
    export.ready_at = datetime.now(timezone.utc)
    # Keep original token hash
    export.download_token_hash = _hash_token(raw_token)
    await session.flush()


async def _notify_export_ready(export: AuditExport) -> None:
    channel = os.getenv("AUDIT_DIGEST_CHANNEL", "log").strip().lower()
    message = (
        f"Audit export {export.id} ready ({export.format}, {export.row_count} rows). "
        f"Expires at {export.expires_at.isoformat() if export.expires_at else 'n/a'}."
    )
    if channel == "slack":
        webhook = os.getenv("AUDIT_DIGEST_SLACK_WEBHOOK", "") or os.getenv("SLO_ALERT_SLACK_WEBHOOK", "")
        if webhook:
            try:
                import httpx
                httpx.post(webhook, json={"text": message}, timeout=5.0)
            except Exception as exc:
                logger.warning(f"Export Slack notify failed: {exc}")
        else:
            logger.info(f"AUDIT_EXPORT_NOTIFY: {message}")
    else:
        logger.info(f"AUDIT_EXPORT_NOTIFY: {message}")


async def get_export_for_download(
    session: AsyncSession,
    export_id: str,
    token: str,
) -> Tuple[AuditExport, bytes, str]:
    """Validate TTL token and return (export, bytes, media_type)."""
    res = await session.execute(select(AuditExport).where(AuditExport.id == export_id))
    export = res.scalar_one_or_none()
    if export is None:
        raise LookupError("Export not found")

    now = datetime.now(timezone.utc)
    expires = export.expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires and now > expires:
        export.status = "expired"
        await session.flush()
        raise PermissionError("Export download link expired")

    if not hmac.compare_digest(export.download_token_hash, _hash_token(token)):
        raise PermissionError("Invalid download token")

    if export.status != "ready" or not export.file_path:
        raise RuntimeError("Export is not ready")

    path = Path(export.file_path)
    if not path.exists():
        raise RuntimeError("Export file missing")

    data = path.read_bytes()
    media = {
        "csv": "text/csv",
        "pdf": "application/pdf",
        "json": "application/json",
    }.get(export.format, "application/octet-stream")
    return export, data, media
