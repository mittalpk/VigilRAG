"""
Locust load test for VigilRAG knowledge query path (US-036 / NFR-001 / NFR-006).

Target profile (5× pilot volume):
- 50 concurrent users
- 5 min ramp-up, 15 min sustained (use --run-time 20m in CI/manual runs)
- Assert via report: p50 ≤ 6s (NFR-006 upper planning bound for synthesized path;
  retrieval-only p50 target ≤ 2s), p90 ≤ 2× target, error rate ≤ 0.5%

Usage:
  locust -f scripts/load/locustfile.py --host http://localhost:8000 \\
         --users 50 --spawn-rate 10 --run-time 20m --headless \\
         --csv=knowledge/08-roadmap/backlog/artifacts/us036-load

Environment:
  VIGILRAG_AUTH_TOKEN   JWT or test token (default: admin_token)
  LOAD_TEST_QUERY       Query string override
"""

from __future__ import annotations

import os
import time

from locust import HttpUser, between, events, task

AUTH_TOKEN = os.getenv("VIGILRAG_AUTH_TOKEN", "admin_token")
QUERY = os.getenv(
    "LOAD_TEST_QUERY",
    "What is the authentication token validation policy?",
)

# NFR-006 planning bounds used for in-run assertions in the report aggregator
P50_TARGET_MS = float(os.getenv("LOAD_P50_TARGET_MS", "6000"))
P90_TARGET_MS = float(os.getenv("LOAD_P90_TARGET_MS", "12000"))
MAX_ERROR_RATE = float(os.getenv("LOAD_MAX_ERROR_RATE", "0.005"))

_latencies_ms: list[float] = []
_errors = 0
_total = 0


class VigilRAGKnowledgeUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.headers = {
            "Authorization": f"Bearer {AUTH_TOKEN}",
            "Content-Type": "application/json",
        }

    @task(5)
    def knowledge_query(self):
        global _errors, _total
        start = time.perf_counter()
        with self.client.post(
            "/api/v1/knowledge/query",
            json={"query": QUERY, "top_k": 5},
            headers=self.headers,
            name="POST /api/v1/knowledge/query",
            catch_response=True,
        ) as response:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            _total += 1
            _latencies_ms.append(elapsed_ms)
            if response.status_code == 200:
                response.success()
            elif response.status_code in (401, 403):
                _errors += 1
                response.failure(f"auth error {response.status_code}")
            elif response.status_code >= 500:
                _errors += 1
                response.failure(f"server error {response.status_code}")
            else:
                _errors += 1
                response.failure(f"unexpected status {response.status_code}")

    @task(1)
    def health_probe(self):
        with self.client.get("/health", name="GET /health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"health {response.status_code}")


@events.quitting.add_listener
def _(environment, **kwargs):
    """Emit a concise pass/fail summary aligned with US-036 acceptance criteria."""
    if not _latencies_ms:
        print("LOAD_TEST_SUMMARY: no samples collected")
        return
    sorted_lat = sorted(_latencies_ms)
    n = len(sorted_lat)
    p50 = sorted_lat[int(0.50 * (n - 1))]
    p90 = sorted_lat[int(0.90 * (n - 1))]
    err_rate = (_errors / _total) if _total else 1.0
    passed = p50 <= P50_TARGET_MS and p90 <= P90_TARGET_MS and err_rate <= MAX_ERROR_RATE
    print(
        "LOAD_TEST_SUMMARY "
        f"samples={n} p50_ms={p50:.1f} p90_ms={p90:.1f} "
        f"error_rate={err_rate:.4f} passed={passed}"
    )
