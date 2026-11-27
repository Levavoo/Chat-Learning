"""Regression coverage for content-safe LangFuse telemetry (#750)."""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from backend_orchestrator.config import Config
from backend_orchestrator.controllers.chat_controller import ChatController
from backend_orchestrator.observability import (
    CONTENT_ATTRIBUTE_NAMES,
    set_content_attribute,
    set_langfuse_trace_context,
    set_langfuse_trace_output,
)
from backend_orchestrator.tools.kb_retrieval import _semantic_search
from backend_orchestrator.validators.guardrail_agent import classify_user_input
from backend_orchestrator.validators.guardrail_validator import _extract_triggered_filters

pytestmark = pytest.mark.unit


class CapturingSpanExporter(SpanExporter):
    def __init__(self):
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        return None


@pytest.fixture
def content_disabled(monkeypatch):
    monkeypatch.setenv("OTEL_INCLUDE_CONTENT", "false")
    Config._instance = None
    yield
    Config._instance = None


def _capturing_provider():
    exporter = CapturingSpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def test_content_export_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("OTEL_INCLUDE_CONTENT", raising=False)
    Config._instance = None
    try:
        assert Config().otel_include_content is False
    finally:
        Config._instance = None


def test_manual_content_attribute_requires_explicit_opt_in(content_disabled, monkeypatch):
    span = MagicMock()

    set_content_attribute(span, "retrieval.query", "private question")

    span.set_attribute.assert_not_called()

    monkeypatch.setenv("OTEL_INCLUDE_CONTENT", "true")
    Config._instance = None
    set_content_attribute(span, "retrieval.query", "approved diagnostic content")

    span.set_attribute.assert_called_once_with("retrieval.query", "approved diagnostic content")


def test_root_observation_sets_input_and_output_regardless_of_content_gate(content_disabled):
    """v4 derives trace.input/output from `langfuse.observation.input/output`; the gate is illusory here."""
    span = MagicMock()

    set_langfuse_trace_context(
        span,
        session_id="session-123",
        user_id="user-456",
        input_text="pension question",
        model="model-id",
        message_id="message-789",
        environment="prod",
    )
    set_langfuse_trace_output(span, "model answer")

    attributes = {call.args[0]: call.args[1] for call in span.set_attribute.call_args_list}
    assert attributes["langfuse.observation.input"] == "pension question"
    assert attributes["langfuse.observation.output"] == "model answer"
    assert "langfuse.trace.input" not in attributes
    assert "langfuse.trace.output" not in attributes
    assert attributes["langfuse.session.id"] == "session-123"
    assert attributes["langfuse.trace.metadata.model"] == "model-id"
    assert attributes["langfuse.environment"] == "prod"


def test_exported_root_span_carries_observation_input_and_output(content_disabled):
    """Export boundary ships root-observation input/output — required by v4's read path."""
    provider, exporter = _capturing_provider()
    tracer = provider.get_tracer(__name__)

    with tracer.start_as_current_span("chat.request") as span:
        set_langfuse_trace_context(
            span,
            session_id="session-123",
            user_id="user-456",
            input_text="pension question",
            model="model-id",
            message_id="message-789",
            environment="prod",
        )
        set_langfuse_trace_output(span, "model answer")

    provider.shutdown()

    assert len(exporter.spans) == 1
    attributes = dict(exporter.spans[0].attributes)
    assert attributes["langfuse.observation.input"] == "pension question"
    assert attributes["langfuse.observation.output"] == "model answer"
    assert "langfuse.trace.input" not in attributes
    assert "langfuse.trace.output" not in attributes
    assert attributes["langfuse.trace.metadata.model"] == "model-id"


def test_controller_export_carries_observation_input_and_output(content_disabled):
    """Simulated chat request writes root-observation input/output regardless of the gate."""
    provider, exporter = _capturing_provider()
    tracer = provider.get_tracer(__name__)
    service = MagicMock()
    service.process_message.return_value = {
        "response_text": "model answer",
        "used_chunks": [],
        "message_id": "message-789",
    }
    app = SimpleNamespace(
        current_event=SimpleNamespace(
            json_body={
                "conversation_id": "session-123",
                "message": {
                    "role": "user",
                    "content": [{"contentType": "text", "body": "pension question"}],
                    "messageId": "message-789",
                },
            },
            request_context=SimpleNamespace(
                authorizer={"claims": {"sub": "user-456", "cognito:username": "test-user"}},
                request_time_epoch=1,
            ),
        )
    )
    config = SimpleNamespace(
        bedrock_model_id="model-id",
        langfuse_environment="prod",
        langfuse_review_tag="",
    )

    with (
        patch("backend_orchestrator.controllers.chat_controller._otel_tracer", tracer),
        patch("backend_orchestrator.controllers.chat_controller.get_config", return_value=config),
        patch("backend_orchestrator.controllers.chat_controller.build_chat_response", return_value={"statusCode": 200}),
    ):
        ChatController(service).handle_chat_request(cast(Any, app))

    provider.shutdown()

    assert len(exporter.spans) == 1
    attributes = dict(exporter.spans[0].attributes)
    assert attributes["langfuse.observation.input"] == "pension question"
    assert attributes["langfuse.observation.output"] == "model answer"
    assert attributes["langfuse.trace.metadata.model"] == "model-id"


def test_semantic_retrieval_export_omits_query_when_content_is_disabled(content_disabled):
    """Retrieval span keeps operational counters without the user's query text."""
    provider, exporter = _capturing_provider()
    tracer = provider.get_tracer(__name__)
    config = SimpleNamespace(
        knowledge_base_id="kb-123",
        aws_region="eu-central-1",
        retrieval_release_id="release-123",
        kb_retrieval_results=3,
    )
    client = MagicMock()
    client.retrieve.return_value = {"retrievalResults": []}

    with (
        patch("backend_orchestrator.tools.kb_retrieval._get_otel_tracer", return_value=tracer),
        patch("backend_orchestrator.tools.kb_retrieval._get_bedrock_client", return_value=client),
    ):
        assert _semantic_search("private pension question", config) == []

    provider.shutdown()

    assert len(exporter.spans) == 1
    attributes = dict(exporter.spans[0].attributes)
    assert "retrieval.query" not in attributes
    assert "private pension question" not in str(attributes)
    assert attributes["retrieval.knowledge_base_id"] == "kb-123"
    assert attributes["retrieval.num_results_returned"] == 0


def test_guardrail_export_omits_model_derived_reason_and_raw_output(content_disabled):
    """Guardrail category observable while its text output stays private."""
    provider, exporter = _capturing_provider()
    tracer = provider.get_tracer(__name__)
    config = SimpleNamespace(aws_region="eu-central-1", guardrail_agent_model_id="guardrail-model")
    client = MagicMock()
    client.converse.return_value = {
        "usage": {"inputTokens": 3, "outputTokens": 2},
        "output": {
            "message": {
                "content": [{"text": '{"category": "BLOCK_STANDARD_1", "reason": "private reason from user input"}'}]
            }
        },
    }

    with (
        patch("backend_orchestrator.validators.guardrail_agent._get_tracer", return_value=tracer),
        patch("backend_orchestrator.validators.guardrail_agent.get_config", return_value=config),
        patch("backend_orchestrator.validators.guardrail_agent._get_bedrock_client", return_value=client),
    ):
        classify_user_input("private pension question")

    provider.shutdown()

    assert len(exporter.spans) == 1
    attributes = dict(exporter.spans[0].attributes)
    assert "guardrail.reason" not in attributes
    assert "guardrail.raw_output" not in attributes
    assert "private reason from user input" not in str(attributes)
    assert attributes["guardrail.category"] == "BLOCK_STANDARD_1"


def test_guardrail_pii_metadata_omits_the_matched_user_text():
    """PII telemetry keeps the entity type but never the raw match."""
    filters = _extract_triggered_filters([
        {"sensitiveInformationPolicy": {"piiEntities": [{"action": "BLOCKED", "type": "EMAIL", "match": "a@b.de"}]}}
    ])

    assert filters == "pii:EMAIL"
    assert "a@b.de" not in filters


def test_content_attribute_names_are_never_set_directly():
    """A raw write to a known content field fails the privacy regression suite.

    Trace-level input/output are intentionally NOT in this set — see
    observability.CONTENT_ATTRIBUTE_NAMES for the v4-read-path rationale.
    """
    expected_names = {
        "retrieval.query",
        "guardrail.reason",
        "guardrail.raw_output",
    }
    assert frozenset(expected_names) == CONTENT_ATTRIBUTE_NAMES

    source_root = Path(__file__).parents[2] / "src" / "backend_orchestrator"
    direct_writes = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "set_attribute"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in CONTENT_ATTRIBUTE_NAMES
            ):
                continue
            direct_writes.append(f"{path.relative_to(source_root)}:{node.lineno}")

    assert direct_writes == []
