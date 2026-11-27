"""Langfuse OTel tracing setup for Lambda cold-start."""

import base64
import json
import re
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import TypedDict

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import MetricUnit, single_metric
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import format_span_id
from pydantic_ai.models.instrumented import InstrumentationSettings

from backend_orchestrator.config import get_config
from backend_orchestrator.otel_propagation import LangfuseAttributeFromBaggageProcessor

logger = Logger(child=True)

# Manual span fields that can carry user/model content; writes must go through set_content_attribute().
# Root-observation input/output are deliberately NOT gated — v4 maps them to trace input/output,
# and pydantic-ai child spans export full content anyway, so gating only the root buys no privacy.
CONTENT_ATTRIBUTE_NAMES = frozenset({
    "retrieval.query",
    "guardrail.reason",
    "guardrail.raw_output",
})

_tracer_provider: TracerProvider | None = None
_instrumentation_settings: InstrumentationSettings | None = None
_langfuse_auth: str | None = None
_langfuse_host: str | None = None
_langfuse_environment: str | None = None


def setup_langfuse_tracing() -> InstrumentationSettings | None:
    """Fetch Langfuse keys from Secrets Manager and configure OTel provider.

    Call once at module level before ChatService() initialisation.
    No-op if LANGFUSE_HOST or LANGFUSE_SECRET_NAME env vars are absent.
    On AWS errors, logs and returns None — Lambda init is not aborted.
    """
    global _tracer_provider, _instrumentation_settings
    config = get_config()
    if not config.langfuse_host or not config.langfuse_secret_name:
        return None

    try:
        secret_str = boto3.client("secretsmanager", region_name=config.aws_region).get_secret_value(
            SecretId=config.langfuse_secret_name
        )["SecretString"]
        keys = json.loads(secret_str)
        auth = base64.b64encode(f"{keys['publicKey']}:{keys['secretKey']}".encode()).decode()
    except Exception:
        logger.exception("Langfuse secret fetch failed — OTel tracing disabled")
        return None

    global _langfuse_auth, _langfuse_host, _langfuse_environment
    _langfuse_auth = auth
    _langfuse_host = config.langfuse_host
    _langfuse_environment = config.langfuse_environment

    exporter = OTLPSpanExporter(
        endpoint=f"{config.langfuse_host}/api/public/otel/v1/traces",
        headers={
            "Authorization": f"Basic {auth}",
            "x-langfuse-ingestion-version": "4",
        },
    )
    # Set the Langfuse environment as a resource attribute so it applies to
    # EVERY span/observation in the trace. Langfuse derives the trace-level
    # `environment` from the root span's environment; a per-span attribute on a
    # non-root span (e.g. our `chat.request` wrapper vs pydantic-ai child spans)
    # is not reliably honoured and falls back to `default`. The environment is a
    # deployment-level property (fixed for the Lambda instance), so the resource
    # attribute is the correct, documented mechanism.
    resource = Resource.create({"langfuse.environment": config.langfuse_environment})
    _tracer_provider = TracerProvider(resource=resource)
    # Must run before the exporter so trace-level attributes are stamped at export time.
    _tracer_provider.add_span_processor(LangfuseAttributeFromBaggageProcessor())
    _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(_tracer_provider)

    _instrumentation_settings = InstrumentationSettings(
        tracer_provider=_tracer_provider,
        include_content=config.otel_include_content,
    )
    return _instrumentation_settings


def content_export_enabled() -> bool:
    """Return whether telemetry is explicitly allowed to contain user or model content.

    This deliberately fails closed when a partial configuration object is supplied in a
    test or future runtime. The setting is shared with pydantic-ai instrumentation.
    """
    return getattr(get_config(), "otel_include_content", False) is True


def set_content_attribute(span: trace.Span, name: str, value: str) -> None:
    """Attach a content-derived OTel attribute only after the explicit privacy opt-in.

    All manual Langfuse/OTel attributes derived from a user message, model response,
    retrieval query, or guardrail output must use this helper. Omitting the attribute
    instead of redacting it ensures disabled content never reaches the export payload.
    """
    if content_export_enabled():
        span.set_attribute(name, value)


def set_langfuse_trace_context(
    span: trace.Span,
    *,
    session_id: str,
    user_id: str,
    input_text: str,
    model: str,
    message_id: str,
    environment: str,
    tags: list[str] | None = None,
    experiment_item_id: str | None = None,
) -> None:
    """Set trace metadata and conditionally attach item-level experiment attrs on the root span.

    When ``experiment_item_id`` is set, stamps the two item-level attributes required by the
    Langfuse v4 Experiments OTel contract. Experiment-level context rides on Baggage.
    """
    span.set_attribute("langfuse.trace.name", "Chatbot Request")
    span.set_attribute("langfuse.session.id", session_id)
    span.set_attribute("langfuse.user.id", user_id)
    # v4 derives trace.input from langfuse.observation.input; langfuse.trace.input is deprecated.
    span.set_attribute("langfuse.observation.input", input_text)
    span.set_attribute("langfuse.trace.metadata.model", model)
    span.set_attribute("langfuse.trace.metadata.message_id", message_id)
    span.set_attribute("langfuse.environment", environment)
    if tags:
        span.set_attribute("langfuse.trace.tags", tags)
    if experiment_item_id:
        span.set_attribute("langfuse.experiment.item.id", experiment_item_id)
        span.set_attribute(
            "langfuse.experiment.item.root_observation_id",
            format_span_id(span.get_span_context().span_id),
        )


def set_langfuse_trace_output(span: trace.Span, output_text: str) -> None:
    """Attach the model output to the root observation after the agent run completes.

    Not gated by ``otel_include_content`` — the same payload is exported on child pydantic-ai spans.
    """
    span.set_attribute("langfuse.observation.output", output_text)


def get_instrumentation_settings() -> InstrumentationSettings | None:
    """Return the configured InstrumentationSettings, or None if tracing is disabled."""
    return _instrumentation_settings


def flush_traces() -> None:
    """Flush buffered spans before Lambda freezes. Call in handler finally block."""
    if _tracer_provider:
        flushed = _tracer_provider.force_flush(timeout_millis=5000)
        if not flushed:
            logger.warning("OTel force_flush timed out — spans may be incomplete")


# CORRECTION omitted on purpose: this writes user/model scores, not retroactive corrections.
VALID_SCORE_DATA_TYPES = frozenset({"NUMERIC", "CATEGORICAL", "BOOLEAN", "TEXT"})

_W3C_TRACE_RE = re.compile(r"[0-9a-f]{32}")

# Tight timeout on a public-facing path. DynamoDB is source-of-truth for feedback; a dropped
# score is a missing dashboard row, never missing user data, so a drop metric beats retry latency.
_SCORE_POST_TIMEOUT_SECONDS = 1.5


class ScoreEvent(TypedDict, total=False):
    """One score-create event in a Langfuse ingestion batch."""

    trace_id: str  # required unless session_id is set
    session_id: str  # scores the Langfuse session instead of a trace
    name: str  # required
    value: float | int | str | bool  # required
    data_type: str  # required; validated against VALID_SCORE_DATA_TYPES
    comment: str | None  # optional
    id: str | None  # optional stable score id
    metadata: dict[str, str]  # optional


def _emit_score_dropped(count: int, mode: str) -> None:
    """Emit one CloudWatch EMF metric per failed batch so an alarm can distinguish causes."""
    with single_metric(
        name="LangfuseScoreDropped",
        unit=MetricUnit.Count,
        value=count,
        namespace="Renate/Backend",
    ) as metric:
        metric.add_dimension(name="Environment", value=_langfuse_environment or "unknown")
        metric.add_dimension(name="FailureMode", value=mode)


def _build_score_event(event: ScoreEvent) -> dict:
    """Validate one score and wrap it in the Langfuse v4 ingestion envelope."""
    data_type = event["data_type"]
    if data_type not in VALID_SCORE_DATA_TYPES:
        raise ValueError(f"invalid Langfuse score data_type: {data_type!r}")
    body: dict = {
        "name": event["name"],
        "value": event["value"],
        "dataType": data_type,
    }
    if "session_id" in event:
        body["sessionId"] = event["session_id"]
    else:
        # Legacy DynamoDB rows carry trace_id as a dashed UUID; strip to match the ingested 32-char hex.
        trace_id = event["trace_id"].replace("-", "")
        if not _W3C_TRACE_RE.fullmatch(trace_id):
            logger.warning("Langfuse trace_id not W3C hex — score will orphan: %r", trace_id)
        body["traceId"] = trace_id
    # v4 scores need their own environment; omitting falls back to "default" and breaks the UI filter.
    if _langfuse_environment:
        body["environment"] = _langfuse_environment
    if event.get("comment") is not None:
        body["comment"] = event["comment"]
    if event.get("id") is not None:
        body["id"] = event["id"]
    if "metadata" in event:
        body["metadata"] = event["metadata"]
    # ISO8601 with ms precision and explicit Z; naive timestamps (utcnow().isoformat()) are rejected by v4.
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {
        "id": str(uuid.uuid4()),
        "type": "score-create",
        "timestamp": timestamp,
        "body": body,
    }


def post_langfuse_scores(events: list[ScoreEvent]) -> None:
    """POST a batch of scores to Langfuse via the v4 ingestion-events endpoint.

    Fail-soft: network/auth/5xx errors are counted as LangfuseScoreDropped and swallowed.
    Validation errors (bad data_type) raise ValueError.
    """
    if not events:
        return
    batch = [_build_score_event(event) for event in events]
    if not _langfuse_auth or not _langfuse_host:
        return
    payload = json.dumps({"batch": batch}).encode()
    req = urllib.request.Request(  # noqa: S310
        f"{_langfuse_host}/api/public/ingestion",
        data=payload,
        headers={"Authorization": f"Basic {_langfuse_auth}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_SCORE_POST_TIMEOUT_SECONDS) as resp:  # noqa: S310
            # urllib raises HTTPError for 4xx/5xx; this branch only catches odd success codes.
            if resp.status not in (200, 201, 207):
                logger.warning("Langfuse ingestion returned %s", resp.status)
                _emit_score_dropped(len(events), "http_5xx" if resp.status >= 500 else "http_4xx")
    except TimeoutError:
        logger.exception("Langfuse ingestion timed out — scores not recorded")
        _emit_score_dropped(len(events), "timeout")
    except urllib.error.HTTPError as e:
        # Catch BEFORE URLError (its parent) so a 503 is attributed to Langfuse, not a network blip.
        logger.exception("Langfuse ingestion returned HTTP %s — scores not recorded", e.code)
        _emit_score_dropped(len(events), "http_5xx" if e.code >= 500 else "http_4xx")
    except urllib.error.URLError as e:
        # URLError wraps connect-timeouts; classify as "timeout" to separate service- vs Lambda-side.
        if isinstance(e.reason, TimeoutError):
            logger.exception("Langfuse ingestion connect timeout — scores not recorded")
            _emit_score_dropped(len(events), "timeout")
        else:
            logger.exception("Langfuse ingestion network error — scores not recorded")
            _emit_score_dropped(len(events), "network")
    except OSError:
        logger.exception("Langfuse ingestion network error — scores not recorded")
        _emit_score_dropped(len(events), "network")
