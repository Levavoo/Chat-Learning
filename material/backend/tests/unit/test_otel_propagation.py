"""Baggage-driven propagation of Langfuse trace attributes to every span (#892).

Langfuse v4 ``events_only + direct`` drops server-side attribute propagation, so
``langfuse.session.id`` and ``langfuse.user.id`` must be stamped on every span
by the client.
"""

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import baggage, context, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from backend_orchestrator.controllers.chat_controller import ChatController
from backend_orchestrator.otel_propagation import (
    LANGFUSE_BAGGAGE_KEYS,
    LangfuseAttributeFromBaggageProcessor,
)

pytestmark = pytest.mark.unit

_FAKE_TRACE_ID_INT = 0xDEADBEEFDEADBEEFDEADBEEFDEADBEEF


class _CapturingExporter(SpanExporter):
    def __init__(self):
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        return None


def _tracer_with_baggage_processor():
    exporter = _CapturingExporter()
    provider = TracerProvider()
    provider.add_span_processor(LangfuseAttributeFromBaggageProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer(__name__), exporter


def test_processor_stamps_baggage_on_nested_spans():
    tracer, exporter = _tracer_with_baggage_processor()

    ctx = baggage.set_baggage("langfuse.session.id", "sess-123")
    ctx = baggage.set_baggage("langfuse.user.id", "user-456", context=ctx)
    token = context.attach(ctx)
    try:
        with tracer.start_as_current_span("root"):
            with tracer.start_as_current_span("child-1"):
                pass
            with tracer.start_as_current_span("child-2"):
                pass
    finally:
        context.detach(token)

    assert [s.name for s in exporter.spans] == ["child-1", "child-2", "root"]
    for span in exporter.spans:
        assert span.attributes["langfuse.session.id"] == "sess-123"
        assert span.attributes["langfuse.user.id"] == "user-456"


def test_processor_is_noop_without_baggage():
    tracer, exporter = _tracer_with_baggage_processor()

    with tracer.start_as_current_span("root"):
        with tracer.start_as_current_span("child"):
            pass

    for span in exporter.spans:
        for key in LANGFUSE_BAGGAGE_KEYS:
            assert key not in span.attributes


def test_processor_skips_empty_baggage_values():
    """Empty string must not be stamped — guards against overwriting a legitimate value further down."""
    tracer, exporter = _tracer_with_baggage_processor()

    ctx = baggage.set_baggage("langfuse.session.id", "")
    ctx = baggage.set_baggage("langfuse.user.id", "", context=ctx)
    token = context.attach(ctx)
    try:
        with tracer.start_as_current_span("root"):
            pass
    finally:
        context.detach(token)

    for span in exporter.spans:
        for key in LANGFUSE_BAGGAGE_KEYS:
            assert key not in span.attributes


def test_controller_wires_baggage_before_root_span_opens():
    """Baggage must be attached before opening ``chat.request`` so every span sees it."""
    tracer, exporter = _tracer_with_baggage_processor()

    captured = {}

    def _side_effect(*args, **kwargs):
        captured["session"] = baggage.get_baggage("langfuse.session.id")
        captured["user"] = baggage.get_baggage("langfuse.user.id")
        with tracer.start_as_current_span("service.child"):
            pass
        return {"response_text": "ok", "used_chunks": [], "message_id": "sess-123#msg"}

    mock_service = MagicMock()
    mock_service.process_message.side_effect = _side_effect

    mock_app = MagicMock()
    mock_app.current_event.json_body = {
        "message": {
            "role": "user",
            "content": [{"contentType": "text", "body": "hi"}],
            "model": "test-model",
            "messageId": "sess-123#msg",
        },
        "conversation_id": "sess-123",
    }
    mock_app.current_event.request_context.authorizer = {
        "claims": {"sub": "user-456", "cognito:username": "user"}
    }
    mock_app.current_event.request_context.request_time_epoch = 1234567890

    with (
        patch("backend_orchestrator.controllers.chat_controller._otel_tracer", tracer),
        patch("backend_orchestrator.controllers.chat_controller.build_chat_response") as mock_build,
    ):
        mock_build.return_value = {"statusCode": 200, "body": "{}"}
        ChatController(mock_service).handle_chat_request(mock_app)

    assert captured == {"session": "sess-123", "user": "user-456"}

    chat_request = next(s for s in exporter.spans if s.name == "chat.request")
    service_child = next(s for s in exporter.spans if s.name == "service.child")
    for span in (chat_request, service_child):
        assert span.attributes["langfuse.session.id"] == "sess-123"
        assert span.attributes["langfuse.user.id"] == "user-456"

    # Detach after the request so the next Lambda invocation does not inherit stale identifiers.
    assert baggage.get_baggage("langfuse.session.id") is None
    assert baggage.get_baggage("langfuse.user.id") is None


def test_processor_tolerates_broken_span(caplog):
    """``on_start`` must swallow exceptions so a broken span never kills a request."""
    processor = LangfuseAttributeFromBaggageProcessor()
    broken = MagicMock(spec=trace.Span)
    broken.set_attribute.side_effect = RuntimeError("broken")

    ctx = baggage.set_baggage("langfuse.session.id", "sess-123")
    processor.on_start(broken, parent_context=ctx)

    assert any("baggage propagation failed" in rec.message for rec in caplog.records)
