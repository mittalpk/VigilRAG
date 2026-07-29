# Audit Log Compliance Sign-Off — US-039 / NFR-004

**Document ID:** `AUDIT_COMPLIANCE_SIGNOFF`  
**Story:** US-039 — Full Compliance-Grade Audit Log  
**Date:** 2026-07-30  
**Status:** Accepted for regulated-data source onboarding gate  

---

## 1. Purpose

This sign-off confirms that VigilRAG’s audit log schema, retention period, export capability, and scheduled digest reporting meet the prerequisites in the [Compliance & Security Framework](COMPLIANCE_SECURITY_FRAMEWORK.md) (audit trail control; regulated-data handling gate) and [Architecture Governance §3](ARCHITECTURE_GOVERNANCE.md#3-phase-gate-approvals) regulated-data onboarding review.

Until this document is accepted, sources classified `internal-sensitive` or `regulated` must not be onboarded (RISK-007 mitigation).

---

## 2. Schema reviewed

| Entity | Purpose | Notes |
|---|---|---|
| `queries` / `answers` / `evidence_items` | Hot audit trail (US-018) | Requester identity, query text, answer, evidence, guardrail flags |
| `archived_queries` | Cold storage after retention | Denormalized Query+Answer+Evidence; retention run linkage |
| `retention_runs` | Retention job audit | Status, cutoff, records archived, errors |
| `audit_exports` | Export jobs + TTL token hash | Format, expiry, async flag, meta-audit linkage via `AUDIT_META:*` rows |
| `scheduled_reports` | Digest destinations | weekly/monthly; log/Slack/email channel |

Full-text search: Postgres GIN on `to_tsvector('english', query_text)`; portable `?q=` filter via `ILIKE` for SQLite/test.

---

## 3. Retention period

| Setting | Value |
|---|---|
| Policy env | `AUDIT_RETENTION_DAYS` |
| Default | **365 days** |
| Enforcement | `scripts/enforce_audit_retention.py` (archive → delete, transactional batches) |

**Acceptance:** 365-day hot retention with mandatory archival before delete is approved for regulated-data onboarding.

---

## 4. Export capability

| Capability | Verification |
|---|---|
| `POST /api/v1/audit/export` (CSV/PDF) | Admin-only; includes Query + Evidence + Answer |
| Download TTL | 1 hour (`AUDIT_EXPORT_TTL_SECONDS=3600`); token hashed at rest |
| Meta-audit | Export request/download logged as `AUDIT_META:*` query rows |
| Large ranges | HTTP 202 + notification channel (`AUDIT_DIGEST_CHANNEL` / Slack webhook) |

---

## 5. Scheduled digests

| Cadence | Entry point |
|---|---|
| Weekly / monthly | `scripts/send_audit_digest.py` / `POST /api/v1/audit/digest` |
| Metrics | Query count, unique identities, flagged responses, guardrail event tallies |
| Delivery | Configurable log / Slack / email (`AUDIT_DIGEST_CHANNEL`, `AUDIT_DIGEST_DESTINATION`) |

---

## 6. Regulated-data onboarding gate (§3 prerequisites)

| Prerequisite | Met? | Evidence |
|---|---|---|
| Audit trail answers “who saw what, when” | Yes | Admin Audit Log UI + detail API |
| Retention policy documented & enforceable | Yes | This sign-off + retention job |
| Compliance-grade export (CSV/PDF) with TTL | Yes | Export API + tests |
| Scheduled compliance digest | Yes | Digest script/service |
| Network isolation for regulated sources | Yes | US-035 Terraform/VNet (dependency) |
| RBAC / admin-only audit surfaces | Yes | US-016/US-017; 401/403 tests |

**Gate decision:** Prerequisites for regulated-data source onboarding related to **audit schema, retention, and export** are **met**. Remaining source-type-specific redaction (Presidio) and classification checks still apply at connector onboarding time per the Compliance Framework.

---

## 7. Sign-off

| Role | Name / System | Decision | Date |
|---|---|---|---|
| Compliance Officer (portfolio) | VigilRAG program compliance checklist | **Accepted** | 2026-07-30 |
| Engineering (implementing story) | US-039 delivery | Implemented & CI-verified | 2026-07-30 |

*This portfolio sign-off is the formal NFR-004 verification artefact for FEAT-08 PI-2. Sponsoring organizations should re-affirm against their own regulatory framework during discovery.*
