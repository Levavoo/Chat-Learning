"""Client-side propagation of Langfuse trace-level attributes to every span.

v4 `events_only + NATIVE_OTEL_BEHAVIOUR=direct` drops server-side attribute propagation,
so this reads a fixed set of attributes from OTel baggage and stamps them onto every span.
"""

from aws_lambda_powertools import Logger
from opentelemetry import baggage
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

logger = Logger(child=True)

LANGFUSE_BAGGAGE_KEYS: tuple[str, ...] = (
    "langfuse.session.id",
    "langfuse.user.id",
    # Experiment-context attributes carried on every span of an item trace;
    # gated hard-off in prod via X-Renate-Eval-Mode in chat_controller.
    "langfuse.experiment.id",
    "langfuse.experiment.name",
    "langfuse.experiment.dataset.id",
    # Item-context attributes: injected into Baggage AFTER chat.request span starts,
    # because root_observation_id must equal the root span's own span id.
    "langfuse.experiment.item.id",
    "langfuse.experiment.item.root_observation_id",
)


class LangfuseAttributeFromBaggageProcessor(SpanProcessor):
    """Stamp Langfuse trace-level baggage onto every started span.

    Must be registered on the TracerProvider before the exporting BatchSpanProcessor.
    """

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        try:
            items = baggage.get_all(parent_context) if parent_context is not None else baggage.get_all()
            for key in LANGFUSE_BAGGAGE_KEYS:
                value = items.get(key)
                if isinstance(value, str) and value:
                    span.set_attribute(key, value)
        except Exception:
            logger.exception("langfuse baggage propagation failed")

    def on_end(self, span: ReadableSpan) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
