from opentelemetry import baggage
from starlette.datastructures import Headers

from miy_api.core.telemetry import bootstrap_telemetry, get_tracer, start_as_current_span
from miy_api.core.trace_context import (
    serialize_current_trace_context,
    start_span_with_trace_context,
)


def test_http_trace_propagates_through_child_and_worker_then_detaches():
    bootstrap_telemetry(service_name="miy-api-test")
    headers = Headers(
        {
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "baggage": "tenant=delivery-hub,feature=rag%20sync",
        }
    )
    with start_as_current_span(
        tracer_name="tests.telemetry", span_name="http", parent_trace_context=headers
    ) as http:
        assert baggage.get_baggage("feature") == "rag sync"
        with start_as_current_span(tracer_name="tests.telemetry", span_name="child") as child:
            assert child.parent.span_id == http.get_span_context().span_id
            serialized = serialize_current_trace_context()
            child_id = child.get_span_context().span_id
    assert baggage.get_baggage("tenant") is None
    assert serialized is not None
    with start_span_with_trace_context(
        tracer=get_tracer("tests.worker"), span_name="worker", parent_trace_context=serialized
    ) as worker:
        assert worker.parent.span_id == child_id
        assert (
            format(worker.get_span_context().trace_id, "032x") == "4bf92f3577b34da6a3ce929d0e0e4736"
        )
        assert baggage.get_baggage("tenant") == "delivery-hub"
        assert baggage.get_baggage("feature") == "rag sync"
    assert baggage.get_baggage("tenant") is None
