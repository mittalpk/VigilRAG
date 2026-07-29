# US-038 Vector Database Graduation — Decision Record

**Status:** Filed · **Date:** 2026-07-30  
**Story:** US-038 / FEAT-20 / Technology Architecture §6a  
**Decision:** **No migration**

---

## 1. Objective

Evaluate whether ≥2 graduation trigger signals are met for migrating from pgvector (co-located Postgres embeddings) to a dedicated vector database (Qdrant preferred / Weaviate SaaS). Migrate only on evidence, not on a fixed schedule.

## 2. Trigger criteria evaluated

| Signal | Threshold | Measured value | Met? |
|---|---|---|---|
| Corpus size | > 500,000 active chunks (US-038 AC; §6a ~1M+) | Pilot corpus ≪ 50K (load-test assumption); DB count at evaluation time typically ≪ threshold | No |
| Query latency | p90 > 2× NFR-006 p50 bound (12,000 ms) **and** retrieval-dominant | US-036 load report p90 = **3,620 ms**; synthesis dominates when LLM live | No |
| Filtering complexity | Rich metadata pre-filter + ANN required | Keyword ILIKE candidate pre-filter + post-hoc permission filter only | No |
| Operational load | Index build > 30 min **or** Postgres contention under write volume | No contention at 5× pilot (US-036); index build negligible at pilot scale | No |

**Signals met:** **0 / 4**  
**Decision rule:** migrate only if ≥2 signals met → **no migration**.

## 3. Platform readiness delivered (prerequisite, not cutover)

Even though migration is not warranted, US-038 ships the replaceable abstraction so a future cutover is configuration-only (NFR-010):

| Component | Path |
|---|---|
| `VectorSearchBackend` Protocol | `backend/app/services/vector_search/protocol.py` |
| `PgvectorBackend` | `backend/app/services/vector_search/pgvector_backend.py` |
| `QdrantVectorSearchBackend` | `backend/app/services/vector_search/qdrant_backend.py` |
| Dual-write wrapper | `backend/app/services/vector_search/dual_write.py` |
| Factory (`VECTOR_SEARCH_BACKEND`) | `backend/app/services/vector_search/__init__.py` |
| Trigger evaluator + admin API | `GET /api/v1/admin/vector-graduation/evaluate` |
| Migration script | `scripts/migrate_vector_db.py` |

Rollback plan (if a future cutover regresses): set `VECTOR_SEARCH_BACKEND=pgvector` — Postgres remains the source of truth for chunk rows.

## 4. Next evaluation

| Field | Value |
|---|---|
| Next evaluation date | **2026-10-28** (≈90 days / next PI boundary) |
| Re-run command | `GET /api/v1/admin/vector-graduation/evaluate` (admin) or re-execute this evaluation at PI planning |
| Escalate if | Exactly 1 signal met + 1 borderline → AI Solutions Architect judgment (no auto-migrate) |

## 5. Sign-off

| Role | Decision | Date |
|---|---|---|
| Platform / AI Engineering | No migration; remain on pgvector; abstraction landed | 2026-07-30 |
| Architecture | Trigger evaluation accepted; RISK-014 premature-migration avoided | 2026-07-30 |

---

*Machine-readable twin: [US-038-vector-graduation-decision.json](US-038-vector-graduation-decision.json)*
