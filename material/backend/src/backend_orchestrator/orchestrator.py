"""Main orchestration entry point for routing chat messages."""

import json

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver, CORSConfig, Response
from aws_lambda_powertools.event_handler.exceptions import ServiceError

from backend_orchestrator.config import get_config
from backend_orchestrator.controllers.chat_controller import ChatController
from backend_orchestrator.controllers.consent_controller import ConsentController
from backend_orchestrator.controllers.session_controller import SessionController
from backend_orchestrator.observability import flush_traces, setup_langfuse_tracing
from backend_orchestrator.services.chat_service import ChatService

logger = Logger()
tracer = Tracer()

config = get_config()

cors_config = CORSConfig(
    allow_origin=config.allowed_origin,
    max_age=config.cors_max_age,
    allow_credentials=True,
)

app = APIGatewayRestResolver(cors=cors_config)


@app.exception_handler(ServiceError)
def _service_error_to_error_body(exc: ServiceError) -> Response:
    """Reshape Powertools-typed exceptions to the repo's {"error": "..."} body.

    Default Powertools serialization is {"statusCode", "message"}, which breaks consumers
    that read body["error"]. Emit the real HTTP status with the familiar body shape.
    """
    return Response(
        status_code=exc.status_code,
        content_type="application/json",
        body=json.dumps({"error": exc.msg}),
    )


_otel_settings = setup_langfuse_tracing()
if _otel_settings:
    from pydantic_ai import Agent as _PydanticAgent

    _PydanticAgent.instrument_all(_otel_settings)

chat_service = ChatService()
chat_controller = ChatController(chat_service)
consent_controller = ConsentController()
session_controller = SessionController(chat_service.conversation_store)


@app.post("/api/chat")
@tracer.capture_method(capture_response=False)
def chat_handler():
    """Handle main chat orchestration requests via controller."""
    return chat_controller.handle_chat_request(app)


@app.put("/api/chat/<session_id>/feedback")
@tracer.capture_method(capture_response=False)
def feedback_handler(session_id: str):
    """Handle feedback updates for a conversation entry."""
    return chat_controller.handle_feedback_request(app, session_id)


@app.post("/api/consent")
@tracer.capture_method(capture_response=False)
def consent_handler():
    """Log user consent for DSFA compliance."""
    return consent_controller.handle_consent_request(app)


@app.delete("/api/session/<conversation_id>")
@tracer.capture_method(capture_response=False)
def delete_session_handler(conversation_id: str):
    """Delete all session data (Widerruf)."""
    return session_controller.handle_delete_session(app, conversation_id)


@app.get("/health")
def health_check():
    """Check the health status of the orchestrator and its dependencies."""
    from backend_orchestrator.health import _check_bedrock, _check_dynamodb, _check_knowledge_base

    checks = {
        "dynamodb": _check_dynamodb(),
        "bedrock": _check_bedrock(),
        "knowledge_base": _check_knowledge_base(),
    }

    statuses = [c["status"] for c in checks.values()]
    if all(s in ("healthy", "skipped") for s in statuses):
        overall = "healthy"
    elif any(s == "unhealthy" for s in statuses):
        overall = "unhealthy"
    else:
        overall = "degraded"

    import json
    import os

    status_code = 200 if overall == "healthy" else 503
    return Response(
        status_code=status_code,
        content_type="application/json",
        body=json.dumps({
            "status": overall,
            "service": "chatbot-backend",
            "environment": os.getenv("ENVIRONMENT", "unknown"),
            "region": os.getenv("REGION", os.getenv("AWS_REGION", "eu-central-1")),
            "checks": checks,
        }),
    )


@logger.inject_lambda_context
@tracer.capture_lambda_handler(capture_response=False)
def lambda_handler(event, context):
    """Resolve the Lambda event using the APIGatewayRestResolver."""
    try:
        from backend_orchestrator.retrieval_diagnostic import (
            is_retrieval_diagnostic_source,
            run_retrieval_diagnostic,
        )

        if is_retrieval_diagnostic_source(event.get("source")):
            return run_retrieval_diagnostic(event)
        return app.resolve(event, context)
    finally:
        flush_traces()
