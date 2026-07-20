# US-036 — Full Observability — Cost Dashboard, SLO Monitoring, Load Test & Chaos-Tested Reliability

## User Story

**As a** Platform Owner / Budget Owner,  
**I want to** view a cost-per-query dashboard, an availability SLO dashboard, and have the platform's reliability validated through a load test and a chaos test that confirms graceful degradation when a source connector fails,  
**So that** the platform's operational costs and availability are transparent and its reliability at scale is proven, not assumed.

---

## Description

This is the PI-2 completion of FEAT-11 (platform hardening), covering the remainder of the NFR-005 (Reliability), NFR-008 (Availability), NFR-009 (Cost optimisation), and the NFR-001 (Scalability) load-test prerequisite deferred from PI-1. It adds a cost-per-query dashboard (using token counts from US-028's OTel spans), an availability SLO dashboard (NFR-008), validates graceful degradation via a chaos test (NFR-005), and executes a load test at 5× pilot volume (NFR-001 prerequisite before enterprise rollout approval).

---

## Business Value

- Gives the Budget Owner the evidence needed for the ROI model: cost per query trending flat or down as volume grows.
- Proves the "graceful degradation" claim (NFR-005): returning a partial answer when one source is unavailable is better than failing the entire request.
- Provides the availability SLO dashboard (NFR-008) required for monthly SLO review: query-path uptime monitored against the 99.5% MVP target.
- Satisfies the NFR-001 load-test prerequisite: the platform must demonstrate it handles 5× pilot volume before enterprise rollout approval.

---

## Acceptance Criteria

**Given** OTel token-cost attributes are captured per query (US-028),  
**When** the cost dashboard is viewed by a platform owner,  
**Then:**
- A dashboard shows: cost per query (in USD, estimated from input/output token counts × model pricing), cost trend over time, and cost breakdown by model (Flash vs. Pro).
- The dashboard is admin-accessible; non-engineers can read it without SQL knowledge.

**Given** the GitHub source connector's API is made unavailable (simulated by revoking the API token),  
**When** a query is submitted that would normally use GitHub content,  
**Then:**
- The query returns a partial answer drawn from wiki content only (if wiki content is relevant).
- The response includes a `source_availability_warning: ["github-unavailable"]` field.
- The response does not fail with a 5xx error.
- The chaos test result is documented and signed off.

**Given** the platform has been running at pilot scale for ≥2 weeks,  
**When** a load test at 5× pilot volume (50 concurrent users, ≤50K chunks corpus) is executed,  
**Then:**
- Query-path p50 latency stays within the NFR-006 target at 5× load.
- No single-instance bottleneck is identified (per NFR-001 audit finding).
- The load test report is filed as a prerequisite artefact for enterprise rollout approval.

**Given** the availability SLO dashboard is deployed,  
**When** the Platform Owner reviews it monthly,  
**Then:**
- Query-path uptime is tracked against the 99.5% MVP target (NFR-008).
- An alert fires when the 30-day rolling availability drops below 99.5%.

---

## Functional Requirements

- NFR-005 (Reliability — graceful degradation).
- NFR-008 (Availability — 99.5% SLO dashboard and alerting).
- NFR-009 (Cost optimisation — cost-per-query dashboard).
- NFR-001 (Scalability — 5× load test, prerequisite for enterprise rollout).

---

## Non-Functional Requirements

- NFR-009 (Cost optimisation) — dashboard trends flat or down per unit query volume growth (reviewed at PI boundary).
- NFR-005 (Reliability) — chaos test validates graceful degradation before enterprise rollout approval.
- NFR-008 (Availability) — uptime monitoring against the 99.5% MVP SLO target; alert on 30-day rolling breach.
- NFR-001 (Scalability) — load test at 5× pilot volume confirms no single-instance bottleneck before enterprise rollout.

---

## Dependencies

- US-028 (OTel tracing — token cost attributes captured here).
- US-022 (Evaluation dashboard — cost dashboard is a sibling page in the admin UI).
- US-006/US-007 (Source connectors — chaos test disables one of these).

---

## Assumptions

- Cost model: Gemini Flash at published per-token pricing; Gemini Pro at published per-token pricing. Token counts are captured as OTel span attributes.
- The cost dashboard reads from the OTel backend's stored spans (Langfuse) or from a dedicated `query_costs` aggregation table populated by a daily job.
- The chaos test is performed manually (not automated in CI); the result is documented as a test report.

---

## Edge Cases

- **Both connectors unavailable simultaneously:** The response should acknowledge that no relevant evidence was found from any available source; do not hallucinate an answer.
- **Cost dashboard shows unexpected spike:** Alert the platform owner; investigate which query types or model calls caused the spike.

---

## Technical Notes / Implementation Considerations

- **Cost calculation:** `cost = (input_tokens * flash_input_price + output_tokens * flash_output_price)` per span where `llm.model = "gemini-flash"`. Similarly for Pro. USD rates from the model's published pricing page.
- **Cost aggregation:** A `query_costs` DB view or materialized view that sums token costs per query from the `answer` records (if token counts are persisted there) or from Langfuse's API.
- **Frontend dashboard:** `CostDashboard.tsx` — a line chart of cost/query per day + a summary card showing total cost this PI.
- **Availability SLO dashboard:** `SLODashboard.tsx` (or a tab within `CostDashboard`) — 30-day rolling uptime percentage from the health-probe endpoint (`/health` on the backend and agent service); alert threshold: < 99.5% triggers a Slack/email alert via an alerting channel already configured.
- **Load test procedure:** Use `locust` or `k6`; target 50 virtual users, 5 minutes ramp-up, 15 minutes sustained; assert p50 latency ≤ NFR-006 target; p90 latency ≤ 2× NFR-006 target; error rate ≤ 0.5%; document and file as a load test report.
- **Chaos test procedure:**
  1. Confirm both connectors are indexed and working.
  2. Revoke/remove the GitHub API token from the secrets store.
  3. Submit a query that normally uses GitHub content.
  4. Confirm: wiki-only partial answer returned; `source_availability_warning` present; no 5xx.
  5. Restore the GitHub token; confirm normal operation resumes.
  6. Document results in a chaos test report filed with the PI-2 exit review.
- **Graceful degradation implementation:** The retrieval endpoint must catch `ConnectorUnavailableError` per connector; exclude unavailable connectors from the merged result set; add the connector name to `source_availability_warning` in the response.

---

## Definition of Done

- [ ] Cost-per-query calculation implemented (from OTel token attributes).
- [ ] `CostDashboard.tsx` frontend page live and admin-accessible.
- [ ] `SLODashboard.tsx` (or tab) showing 30-day rolling uptime against the 99.5% MVP SLO target.
- [ ] Availability alert configured: fires when 30-day uptime drops below 99.5%.
- [ ] Load test at 5× pilot volume executed; results documented in a load test report (p50 ≤ NFR-006 target, error rate ≤ 0.5%).
- [ ] No single-instance bottleneck identified in load test results.
- [ ] Load test report filed as a prerequisite artefact for enterprise rollout approval.
- [ ] Graceful degradation implemented: `ConnectorUnavailableError` caught; partial answer returned with `source_availability_warning`.
- [ ] Chaos test executed and documented (GitHub connector simulated unavailable → partial wiki answer returned, no 5xx).
- [ ] Chaos test report filed with PI-2 exit review package.
- [ ] NFR-005, NFR-008, NFR-009, and NFR-001 (load test) sign-off at PI-2 boundary review.

---

## Priority

**High** in PI-2 (NFR-005 chaos test is a non-negotiable PI-2 objective).

## Estimated Effort

**M (Medium)** — ~3–4 days (cost calculation, frontend dashboard, graceful degradation, chaos test execution and report).

## Related Epics / Features

- FEAT-11 (Platform hardening — reliability + cost + availability + scalability)
- NFR-001 (Scalability — load test prerequisite)
- NFR-005 (Reliability — chaos test)
- NFR-008 (Availability — SLO dashboard)
- NFR-009 (Cost optimisation — cost dashboard)
