#!/usr/bin/env python3
"""Generate OpenAPI spec from Pydantic models into backend/openapi.yaml."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter

from backend_orchestrator.models import ChatInput, ChatOutput, MessageFeedback
from backend_orchestrator.models.api_models import AnalyticsResponse, DocumentInventoryResponse

OPENAPI_VERSION = "3.1.0"
API_VERSION = "1.0.0"
API_TITLE = "Digibro Chat API"


def rewrite_refs(obj: Any) -> Any:
    """Recursively rewrite ``$defs`` refs to ``components/schemas`` refs."""
    if isinstance(obj, dict):
        if "$ref" in obj and obj["$ref"].startswith("#/$defs/"):
            obj["$ref"] = obj["$ref"].replace("#/$defs/", "#/components/schemas/")
        return {k: rewrite_refs(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rewrite_refs(item) for item in obj]
    return obj


def generate_openapi_spec() -> dict:
    """Generate OpenAPI specification from Pydantic models."""
    chat_input_schema = TypeAdapter(ChatInput).json_schema(mode="serialization")
    chat_output_schema = TypeAdapter(ChatOutput).json_schema(mode="serialization")
    feedback_schema = TypeAdapter(MessageFeedback).json_schema(mode="serialization")
    analytics_schema = TypeAdapter(AnalyticsResponse).json_schema(mode="serialization")
    documents_schema = TypeAdapter(DocumentInventoryResponse).json_schema(mode="serialization")

    all_defs = {}
    for schema in [chat_input_schema, chat_output_schema, feedback_schema, analytics_schema, documents_schema]:
        if "$defs" in schema:
            all_defs.update(schema.pop("$defs"))

    chat_input_schema = rewrite_refs(chat_input_schema)
    chat_output_schema = rewrite_refs(chat_output_schema)
    feedback_schema = rewrite_refs(feedback_schema)
    analytics_schema = rewrite_refs(analytics_schema)
    documents_schema = rewrite_refs(documents_schema)
    all_defs = rewrite_refs(all_defs)

    error_response = {
        "type": "object",
        "properties": {
            "error": {"type": "string"},
            "message": {"type": "string"},
        },
        "required": ["error"],
    }

    health_response = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["healthy"]},
        },
        "required": ["status"],
    }

    spec = {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": API_TITLE,
            "version": API_VERSION,
        },
        "paths": {
            "/api/chat": {
                "post": {
                    "operationId": "chat",
                    "summary": "Send a chat message",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ChatInput"},
                            },
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Successful response",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ChatOutput"},
                                },
                            },
                        },
                        "400": {
                            "description": "Bad request",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                                },
                            },
                        },
                        "409": {
                            "description": "Conversation limit reached, start a new conversation",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                                },
                            },
                        },
                        "500": {
                            "description": "Internal server error",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                                },
                            },
                        },
                        "503": {
                            "description": "Conversation history unavailable, request rejected",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                                },
                            },
                        },
                    },
                },
            },
            "/api/chat/{session_id}/feedback": {
                "put": {
                    "operationId": "submitFeedback",
                    "summary": "Submit feedback for a chat message",
                    "parameters": [
                        {
                            "name": "session_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "The session ID of the conversation",
                        },
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/FeedbackRequest"},
                            },
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Feedback submitted successfully",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/FeedbackResponse"},
                                },
                            },
                        },
                        "400": {
                            "description": "Bad request",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                                },
                            },
                        },
                    },
                },
            },
            "/api/analytics": {
                "get": {
                    "operationId": "getAnalytics",
                    "summary": "Get aggregated analytics for the editorial dashboard",
                    "parameters": [
                        {
                            "name": "from_ts",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                            "description": "Start timestamp (Unix ms)",
                        },
                        {
                            "name": "to_ts",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                            "description": "End timestamp (Unix ms)",
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Analytics data",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AnalyticsResponse"},
                                },
                            },
                        },
                    },
                },
            },
            "/api/analytics/documents": {
                "get": {
                    "operationId": "getDocuments",
                    "summary": "Get document inventory from the Agent-Search-Index",
                    "responses": {
                        "200": {
                            "description": "Document inventory",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/DocumentInventoryResponse"},
                                },
                            },
                        },
                    },
                },
            },
            "/api/consent": {
                "post": {
                    "operationId": "logConsent",
                    "summary": "Log user consent for DSFA compliance",
                    "description": "Records that the user has given informed consent. Best-effort logging — always returns 200.",
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ConsentRequest"},
                            },
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Consent logged successfully",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ConsentResponse"},
                                },
                            },
                        },
                    },
                },
            },
            "/api/session/{conversationId}": {
                "delete": {
                    "operationId": "deleteSession",
                    "summary": "Delete all session data (Widerruf)",
                    "description": "Deletes all conversation items for the given session. Best-effort — always returns 200.",
                    "parameters": [
                        {
                            "name": "conversationId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "format": "uuid"},
                            "description": "The conversation/session UUID to delete",
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Session deleted (or not found — always 200)",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/SessionDeleteResponse"},
                                },
                            },
                        },
                        "400": {
                            "description": "Invalid conversation ID format",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                                },
                            },
                        },
                    },
                },
            },
            "/health": {
                "get": {
                    "operationId": "healthCheck",
                    "summary": "Check API health status",
                    "responses": {
                        "200": {
                            "description": "Service is healthy",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/HealthResponse"},
                                },
                            },
                        },
                    },
                },
            },
        },
        "components": {
            "schemas": {
                "ChatInput": chat_input_schema,
                "ChatOutput": chat_output_schema,
                "MessageFeedback": feedback_schema,
                "FeedbackRequest": {
                    "type": "object",
                    "properties": {
                        "messageId": {"type": "string"},
                        "feedback": {"$ref": "#/components/schemas/MessageFeedback"},
                    },
                    "required": ["feedback"],
                },
                "FeedbackResponse": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                    },
                    "required": ["success"],
                },
                "ConsentResponse": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["ok"]},
                    },
                    "required": ["status"],
                },
                "ConsentRequest": {
                    "type": "object",
                    "properties": {
                        "sessionId": {
                            "type": "string",
                            "description": "Optional session UUID to link consent to session",
                        },
                    },
                },
                "SessionDeleteResponse": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["ok"]},
                    },
                    "required": ["status"],
                },
                "ErrorResponse": error_response,
                "AnalyticsResponse": analytics_schema,
                "DocumentInventoryResponse": documents_schema,
                "HealthResponse": health_response,
                **all_defs,
            },
        },
    }

    return spec


def main() -> None:
    """Write the generated spec to backend/openapi.yaml."""
    spec = generate_openapi_spec()

    output_path = Path(__file__).parent.parent / "openapi.yaml"
    with output_path.open("w", encoding="utf-8") as f:
        yaml.dump(spec, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"Generated OpenAPI spec: {output_path}")


if __name__ == "__main__":
    main()
