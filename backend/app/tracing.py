"""
VigilRAG Backend Service OpenTelemetry Tracing Module (US-028 / NFR-007 / NFR-009).
Provides distributed tracing instrumentation, span context creation, attributes setting,
and OTLP export configuration.
"""

from contextlib import contextmanager
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TRACER = None
_SPANS_HISTORY = []  # In-memory history for testing/inspection


def init_tracer(service_name: str = "vigilrag-backend"):
    """
    Initializes OpenTelemetry TracerProvider with OTLP or in-memory exporter.
    """
    global _TRACER
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("LANGFUSE_HOST")
        if otlp_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")
                provider.add_span_processor(BatchSpanProcessor(exporter))
                logger.info(f"OpenTelemetry OTLP exporter configured for endpoint: {otlp_endpoint}")
            except Exception as exc:
                logger.warning(f"Failed to load OTLPSpanExporter ({exc})")

        trace.set_tracer_provider(provider)
        _TRACER = trace.get_tracer(service_name)
        return _TRACER
    except Exception as exc:
        logger.warning(f"OpenTelemetry SDK initialization warning ({exc}); using fallback tracer.")
        _TRACER = None
        return None


def get_tracer():
    global _TRACER
    if _TRACER is None:
        init_tracer()
    return _TRACER


@contextmanager
def trace_span(span_name: str, attributes: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
    """
    Context manager to wrap a section of code in an OpenTelemetry span.
    Captures duration, attributes, trace_id, and exceptions.
    """
    start_time = time.time()
    span_obj = None
    tracer = get_tracer()

    span_record = {
        "name": span_name,
        "trace_id": trace_id,
        "attributes": dict(attributes or {}),
        "start_time": start_time,
        "end_time": None,
        "duration_ms": 0,
        "error": None,
    }

    if tracer:
        try:
            span_obj = tracer.start_span(span_name)
            if trace_id:
                span_obj.set_attribute("trace_id", trace_id)
            if attributes:
                for k, v in attributes.items():
                    if v is not None:
                        span_obj.set_attribute(k, v)
        except Exception as exc:
            logger.debug(f"Span start exception: {exc}")

    try:
        yield span_obj
    except Exception as exc:
        span_record["error"] = str(exc)
        if span_obj:
            try:
                span_obj.record_exception(exc)
                span_obj.set_attribute("error", True)
                span_obj.set_attribute("error.message", str(exc))
            except Exception:
                pass
        raise
    finally:
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        span_record["end_time"] = end_time
        span_record["duration_ms"] = duration_ms
        if "latency_ms" not in span_record["attributes"]:
            span_record["attributes"]["latency_ms"] = duration_ms

        _SPANS_HISTORY.append(span_record)

        if span_obj:
            try:
                span_obj.set_attribute("latency_ms", duration_ms)
                span_obj.end()
            except Exception:
                pass
