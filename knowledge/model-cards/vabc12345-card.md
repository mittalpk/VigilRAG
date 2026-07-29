# Model / System Card — VigilRAG Pipeline vabc123456789def

**Published Date:** 2026-07-29 21:00:24 UTC  
**Pipeline Version (Git SHA):** `abc123456789def`  
**Evaluation Run ID:** `eval-run-abc12345`  
**Dataset Version:** `v1.0`  
**AI Risk Tier:** Medium / High (Enterprise Knowledge Retrieval)

---

## 1. System Overview & Purpose

VigilRAG is a hybrid Retrieval-Augmented Generation (RAG) platform designed to provide accurate, permission-aware answers to user queries by retrieving knowledge from live company repositories (GitHub code, Confluence wikis, local documentation, and relational database schemas).

## 2. Capabilities & Architecture

- **Hybrid Retrieval:** Vector similarity search merged with BM25 keyword search using Reciprocal Rank Fusion (RRF).
- **Retrieval Reranking:** Cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`) for candidate evidence refinement.
- **Multi-Agent Orchestration:** LangGraph iterative planning, tool execution, and sufficiency evaluation loop.
- **Permission & Security:** Per-chunk ACL evaluation with fail-closed access control and Key Vault secret references.
- **Freshness & Conflict Signaling:** Staleness detection (>90 days) and cross-source contradiction evaluation.

---

## 3. Known Limitations

- **Structured Search Scope:** Relational database introspection is restricted to `information_schema` table/column metadata and does not execute arbitrary SQL DML/DDL against user databases.
- **Context Window Limits:** Single table schema representations exceeding 100 columns are truncated with warning signals.
- **Language Scope:** Optimized for English documentation and standard programming source code.

---

## 4. Evaluation Performance & Quality Metrics

The following metrics were evaluated against golden dataset `v1.0` using RAGAS criteria:

| Metric | Score | Target Threshold | Pass Status |
|---|---|---|---|
| **Faithfulness** | 0.8850 | ≥ 0.8500 | PASSED |
| **Context Precision** | 0.8520 | ≥ 0.8000 | PASSED |
| **Context Recall** | 0.8340 | ≥ 0.8000 | PASSED |
| **Average Latency** | 345.0 ms | ≤ 2000.0 ms | PASSED |

---

## 5. Governance Framework Mapping (NIST AI RMF & ISO/IEC 42001)

| Governance Function | Standard Reference | VigilRAG Implementation Details |
|---|---|---|
| **GOVERN 1.1** | NIST AI RMF / ISO 42001 Cl. 5 | RBAC & Admin-only endpoints (`require_role(["admin"])`), secret management via Azure Key Vault. |
| **MAP 1.2** | NIST AI RMF / ISO 42001 Cl. 6 | Strict permission evaluation (`PermissionEvaluator`) failing closed on missing/null ACLs. |
| **MEASURE 2.1** | NIST AI RMF / ISO 42001 Cl. 9 | CI-gated RAGAS evaluation harness (`scripts/run_evaluation.py`) enforcing quality baselines. |
| **MANAGE 3.2** | NIST AI RMF / ISO 42001 Cl. 8 | Freshness conflict evaluator signaling source contradictions and staleness (>90 days). |

---

## 6. Audit & Traceability Sign-off

- **Evaluator Harness:** `scripts/run_evaluation.py`
- **Audit Logging:** Enabled (`AuditLog` sqlite/pg database backing all queries and guardrail interventions)
- **Tracing:** OpenTelemetry distributed tracing enabled (`trace_id` headers propagation)
