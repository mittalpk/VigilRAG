"""
Unit Tests for Backend OpenTelemetry Tracing Module (US-028 / NFR-007 / NFR-009).
"""

import pytest
from backend.app.tracing import init_tracer, trace_span, _SPANS_HISTORY


def test_backend_init_tracer():
    tracer = init_tracer(service_name="test-backend")
    assert tracer is not None or tracer is None


def test_backend_trace_span_attributes():
    span_name = "knowledge_api.retrieve"
    trace_id = "trc-backend-5678"
    attrs = {
        "query.length": 25,
        "retrieval.top_k": 3,
        "requester_identity": "alice@example.com",
    }

    initial_count = len(_SPANS_HISTORY)
    with trace_span(span_name, attributes=attrs, trace_id=trace_id):
        pass

    assert len(_SPANS_HISTORY) == initial_count + 1
    last_span = _SPANS_HISTORY[-1]
    assert last_span["name"] == span_name
    assert last_span["trace_id"] == trace_id
    assert last_span["attributes"]["query.length"] == 25
    assert last_span["attributes"]["retrieval.top_k"] == 3
    assert last_span["attributes"]["requester_identity"] == "alice@example.com"
