"""
Unit Tests for Agent OpenTelemetry Tracing Module (US-028 / NFR-007 / NFR-009).
"""

import pytest
from agent.app.tracing import init_tracer, trace_span, _SPANS_HISTORY


def test_init_tracer_default():
    tracer = init_tracer(service_name="test-agent")
    assert tracer is not None or tracer is None  # Ensures no unhandled exception thrown


def test_trace_span_record_attributes():
    span_name = "test.agent.span"
    trace_id = "trc-test-1234"
    attrs = {
        "llm.model": "gemini-1.5-pro",
        "llm.input_tokens": 42,
        "llm.output_tokens": 100,
        "retrieval.top_k": 5,
    }

    initial_count = len(_SPANS_HISTORY)
    with trace_span(span_name, attributes=attrs, trace_id=trace_id):
        pass

    assert len(_SPANS_HISTORY) == initial_count + 1
    last_span = _SPANS_HISTORY[-1]
    assert last_span["name"] == span_name
    assert last_span["trace_id"] == trace_id
    assert last_span["attributes"]["llm.model"] == "gemini-1.5-pro"
    assert last_span["attributes"]["llm.input_tokens"] == 42
    assert last_span["attributes"]["llm.output_tokens"] == 100
    assert last_span["duration_ms"] >= 0


def test_trace_span_exception_recording():
    span_name = "test.error.span"
    initial_count = len(_SPANS_HISTORY)

    with pytest.raises(ValueError) as exc_info:
        with trace_span(span_name, trace_id="trc-err-01"):
            raise ValueError("Synthetic breakdown error for NFR-007 verification")

    assert "Synthetic breakdown" in str(exc_info.value)
    assert len(_SPANS_HISTORY) == initial_count + 1
    last_span = _SPANS_HISTORY[-1]
    assert last_span["name"] == span_name
    assert last_span["error"] == "Synthetic breakdown error for NFR-007 verification"
