# US-029 — Platform Audit Gap Reconciliation & Remediation

**Status:** Completed & Archived

## User Story

**As a** Lead System Architect & Compliance Officer,  
**I want to** audit and reconcile all functional, non-functional, security, and infrastructure gaps identified in the PI-1/PI-2 gap analysis,  
**So that** the platform upholds its compliance, RBAC, auditability, data integrity, and CI requirements before broad pilot deployment.

---

## Description

Following the comprehensive audit of all 28 initial user stories (US-001 through US-028), 9 specific functional, security, NFR, and CI gaps were identified. This story covers the systematic remediation, verification, and migration of those items across backend, agent, frontend, and CI workflow configurations.

---

## Acceptance Criteria

**Given** the PI-1/PI-2 system codebase,  
**When** the remediation suite is executed,  
**Then:**
1. **GAP-F01:** `HybridRetrievalResponse` returns `query_id` alongside `trace_id` so frontend feedback submission connects directly to valid query records without HTTP 404 errors.
2. **GAP-F02:** `GET /api/v1/audit/queries/{query_id}` performs a DB lookup against `Chunk.content` to return real excerpt text rather than placeholder strings.
3. **GAP-F03:** `POST /api/v1/knowledge/query` and `POST /api/v1/agent/run` endpoints enforce `require_role(["admin", "user"])`, rejecting `viewer` users with HTTP 403 Forbidden.
4. **GAP-N04:** Alembic migration `0006_feedback_tables.py` creates `feedback` and `feedback_review_items` tables for production deployments.
5. **GAP-N02:** Role assignments in `assign_user_role` persist structured `QueryRecord` audit entries in the database.
6. **GAP-N03:** `Presidio` initialization failure raises HTTP 503 Service Unavailable (fail-closed) during PII redaction checks.
7. **GAP-N05:** `backend/app/main.py` uses `@asynccontextmanager lifespan` instead of deprecated `@app.on_event` handlers.
8. **GAP-N01:** The `agent.synthesise` span includes the `latency_ms` attribute.
9. **GAP-T03 & GAP-T04:** GitHub Actions CI downloads spaCy `en_core_web_lg` model and installs `pytest-asyncio` for agent/guardrails test jobs.

---

## Technical Implementation Summary

- **Backend Schemas:** Added `query_id: str` to `HybridRetrievalResponse` in `backend/app/schemas.py`.
- **Knowledge & Agent Routers:** Wired `query_id` in `knowledge.py` and added `require_role` guards to query routes.
- **Audit Router:** Added SQLAlchemy join on `Chunk.content` in `get_audit_query_detail`.
- **Database Migrations:** Created `backend/alembic/versions/0006_feedback_tables.py`.
- **RBAC Service:** Added DB audit persistence in `assign_user_role`.
- **Guardrails:** Updated `GuardrailsClient` to enforce fail-closed HTTP 503 if Presidio engines fail to initialize.
- **Application Lifespan:** Converted `main.py` to `lifespan` context manager.
- **CI Pipeline:** Updated `.github/workflows/ci.yml` dependencies and spaCy downloads.
- **Tests:** Created comprehensive unit test suite `backend/tests/test_gap_fixes.py` (10/10 passing).

---

## Definition of Done

- [x] All 9 gaps implemented and verified locally.
- [x] Unit test suite `test_gap_fixes.py` 100% passing.
- [x] Frontend TypeScript build `npx tsc` 100% passing.
- [x] Feature branch `feature/gap-analysis-fixes` committed and pushed.
- [x] Execution runbook updated and story moved to `knowledge/08-roadmap/backlog/done/`.
