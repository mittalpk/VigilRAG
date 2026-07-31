# VigilRAG — Governance-Gated Enterprise Agentic RAG Platform

[![License: PolyForm Shield 1.0.0](https://img.shields.io/badge/License-PolyForm%20Shield%201.0.0-purple.svg)](LICENSE)
[![CI](https://github.com/mittalpk/VigilRAG/actions/workflows/ci.yml/badge.svg)](https://github.com/mittalpk/VigilRAG/actions/workflows/ci.yml)

A **cloud-native knowledge retrieval platform** that unifies enterprise data sources — code repositories, policy documents, databases, and wikis — into a single, traceable, LLM-ready API.

## Overview

VigilRAG addresses a core enterprise challenge: **knowledge is scattered across disconnected systems**. Employees and AI agents alike waste time context-switching between GitHub, Confluence, databases, and documentation portals — or worse, AI agents get broad, ungoverned access to those systems because no safe unified interface exists. VigilRAG's target design provides a unified retrieval layer and a governed multi-agent reasoning engine on top of it, with a hard trust boundary between reasoning and data access.

## Project Status

| Area | Current state | Next hardening |
|---|---|---|
| Retrieval | **Hybrid semantic + keyword (RRF)** over Postgres/pgvector with citations, reranking, freshness/conflict signals | Optional GraphRAG engine (Phase 4+); thin `QueryRouter` already pluggable |
| Agent reasoning | **Iterative** LangGraph loop with `max_iterations`, guardrails (injection/PII/output), MCP tool interface | Multi-engine routing for relationship-shaped queries |
| Database source | **Implemented** — Postgres schema connector + Graph-Ready chunk metadata | Broader structured-source types as needed |
| Trust boundary (agent ↔ data) | **Enforced** — agent holds no source-system credentials; service key + JWT | Unchanged architectural strength |
| CI/CD | Pytest + frontend build + **RAGAS evaluation-gate** on push/PR (no auto-deploy) | Keep eval corpus growing via feedback loop |
| Access control | **RBAC + multi-user JWT**; admin-seeded bootstrap | Optional IdP federation |
| Audit / compliance | Hot audit log + retention archive, CSV/PDF export (1h TTL), digests | Ops scheduling for retention/digest jobs |

This table reflects the repository as of US-039. Historical audit notes remain in [`knowledge/VigilRAG_AUDIT.md`](knowledge/VigilRAG_AUDIT.md); the living task list is [`knowledge/08-roadmap/EXECUTION_RUNBOOK.md`](knowledge/08-roadmap/EXECUTION_RUNBOOK.md).

---

## Architecture

The platform is structured as a **4-layer cloud-native system**:

### Layer 1 — Data Sources
Live enterprise systems: **GitHub** (code), **Azure Blob Storage** (policy docs, wikis), **SQL Databases** (schema metadata via the structured connector), **Confluence** (internal documentation, with local/demo fallbacks).

### Layer 2 — Knowledge API (Retrieval)
The `POST /api/v1/knowledge/query` endpoint is the **single source-of-truth interface**. It:
- Routes through a modular **`QueryRouter`** (vector hybrid today; graph engine stub for future GraphRAG).
- Enforces a trust boundary: all retrieval is read-only; the agent tier never touches source-system credentials directly.
- Returns structured, traceable JSON: evidence chunks, `query_id` / `trace_id`, groundedness score, and availability warnings.

### Layer 3 — Agent Orchestrator
Built on **LangGraph + Gemini**, with iterative evaluate/re-plan bounded by `max_iterations`, plus MCP (`/mcp/v1/tools/vigilrag_query`) for machine consumers.

### Layer 4 — Application Layer
A **React 18 + TypeScript** dashboard (query, citations, feedback, audit/export, evaluation, cost/SLO, sources, model cards).

---

## Technical Stack

| Layer         | Technology                              | Role |
|---------------|------------------------------------------|------|
| Frontend      | React 18, TypeScript, Vite, Nginx        | Interactive knowledge dashboard |
| Backend API   | Python 3.12, FastAPI, Pydantic, SQLAlchemy, pgvector | API gateway + hybrid retrieval |
| Agent Service | LangGraph, Gemini 2.5 Flash / Pro         | Multi-step reasoning engine |
| Auth          | JWT + RBAC + shared internal API key      | Token-based & service-key security boundary |
| Infrastructure| Terraform, Azure Container Apps (enterprise profile) or Netlify + Koyeb + Supabase (demo profile) | See [Deployment](#deployment) |

---

## Documentation

All project documentation lives in **[`knowledge/`](knowledge/)** — the enterprise solution-architecture knowledge base. Start at [`knowledge/README.md`](knowledge/README.md).

---

## Quick Start (Local)

```bash
# 1. Configure environment — required secrets must be set or services refuse to start
cp .env.example .env
# Edit .env and set at least:
#   INTERNAL_API_KEY, SECRET_KEY, ADMIN_PASSWORD
#   GOOGLE_API_KEY (agent) and GITHUB_PAT (optional for live GitHub)

# 2. Install Python deps (includes reportlab for PDF audit export)
python3 -m pip install -r backend/requirements.txt -r agent/requirements.txt

# 3. Seed an admin user (uses ADMIN_PASSWORD from .env)
PYTHONPATH=. python3 scripts/seed_admin.py

# 4. Start services
docker compose up --build
# Or run backend/agent/frontend processes individually against the same .env
```

| Service | URL |
|---|---|
| Frontend Dashboard | `http://localhost:15173` |
| Backend API (Swagger) | `http://localhost:18000/docs` |
| Agent Service | `http://localhost:18001/docs` |
| Jaeger UI | `http://localhost:16687` |

> Host ports are offset (`18000`/`18001`/`15173`/`16687`) so VigilRAG can run alongside other local stacks that already bind `:8000` / Jaeger `:4317`.


Log in with the seeded admin identity, then use **Knowledge** → query → citations/feedback, **Audit Log** for export, and admin dashboards as needed.

## Testing

```bash
python3 -m pytest backend/tests agent/tests -v   # backend + agent
cd frontend && npm ci && npm run build            # frontend type-check + build
```

The same commands run in CI on every push and pull request to `main` — see [`.github/workflows/ci.yml`](.github/workflows/ci.yml). CI validates and gates; it does not deploy.

## Deployment

Two deployment profiles exist, documented in [`knowledge/04-solution-architecture/TECHNOLOGY_ARCHITECTURE.md §6`](knowledge/04-solution-architecture/TECHNOLOGY_ARCHITECTURE.md#6-deployment-profiles):

| Profile | Stack | Use case | Runbook |
|---|---|---|---|
| Enterprise | Azure Container Apps + Terraform, managed Postgres/Redis/Key Vault | A real pilot deployment meeting the project's non-functional requirements | [`knowledge/04-solution-architecture/deployment/AZURE_DEPLOYMENT.md`](knowledge/04-solution-architecture/deployment/AZURE_DEPLOYMENT.md) |
| Demo | Netlify (frontend) + Koyeb (backend/agent, free tier) + Supabase (Postgres) | Low-cost public demo hosting; **not** representative of production scale, availability, or security posture | [`knowledge/04-solution-architecture/deployment/deployment_plan.md`](knowledge/04-solution-architecture/deployment/deployment_plan.md) |

Neither profile is wired to automatic deployment from this repository's CI — deployment is a deliberate, manual action following the linked runbook.

## Contributing

Issues and PRs are welcome; see [`knowledge/07-governance-risk/ARCHITECTURE_GOVERNANCE.md`](knowledge/07-governance-risk/ARCHITECTURE_GOVERNANCE.md) for the change-control process any architecture-significant contribution goes through.

## License

PolyForm Shield License 1.0.0 — see [LICENSE](LICENSE).
