"""Local development server for the Backend Orchestrator.

This module provides a FastAPI application that wraps the orchestrator logic
and mocks AWS services to allow offline development.
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend_orchestrator.response_parser import build_chat_response
from backend_orchestrator.utils.session_masking import sanitize_error_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not os.getenv("KNOWLEDGE_BASE_ID"):
    os.environ["KNOWLEDGE_BASE_ID"] = "mock-kb-id"
if not os.getenv("DB_TABLE_NAME"):
    os.environ["DB_TABLE_NAME"] = "mock-db-table"

MOCK_AGENT_RESPONSE = {
    "response": json.dumps({
        "result": {
            "content": [{"text": "This is a response from the local emulator. I am simulating the Bedrock Agent."}]
        },
        "relatedDocuments": [
            {
                "documentId": "doc1",
                "sourceName": "Mock Document 1",
                "content": {"text": "This is content from doc 1."},
            }
        ],
        "usedChunks": [{"documentId": "doc1", "sourceName": "Mock Document 1"}],
    }),
    "usedChunks": [],
}


class MockBedrockAgentClient:
    """Mock client for Bedrock Agent Runtime."""

    def invoke_agent(self, session_id: str, prompt: str, enable_trace: bool = False) -> dict:
        """Return a static mock response."""
        logger.info(f"Mock invoke_agent called with session_id={session_id}, prompt={prompt}")
        return MOCK_AGENT_RESPONSE


try:
    from backend_orchestrator.response_parser import parse_agent_response
    from backend_orchestrator.services.chat_service import ChatService
    from backend_orchestrator.validation import extract_message_text
except ImportError:
    logger.warning("Could not import required modules. Ensure dependencies are installed.")
    ChatService = None  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]
    parse_agent_response = None  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
    extract_message_text = None  # type: ignore[assignment]  # ty: ignore[invalid-assignment]


# Initialize chat service at module level
chat_service = ChatService() if ChatService else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events."""
    # No need to patch anything in the new architecture
    logger.info("Local dev server started with ChatService")
    yield
    logging.info("Shutting down local dev server")


app = FastAPI(title="Backend Orchestrator Local Dev", lifespan=lifespan)

# CORS configuration
origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:4200",
    "http://localhost:4201",
    "http://127.0.0.1:4200",
    "http://127.0.0.1:4201",
    "http://0.0.0.0:4200",
]

app.add_middleware(
    CORSMiddleware,  # type: ignore[invalid-argument-type]
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "mode": "local-emulator"}


@app.post("/api/chat")
async def chat(request: Request):
    """Handle chat requests compatible with the Lambda handler."""
    if not chat_service:
        raise HTTPException(status_code=500, detail="ChatService not initialized")

    try:
        raw_body = await request.body()
        if not raw_body:
            return JSONResponse(status_code=400, content={"error": "Empty request body"})
        body = json.loads(raw_body)
        message = extract_message_text(body)
        session_id = body.get("conversationId", body.get("conversation_id", "local-session"))
        message_id = None
        message_payload = body.get("message")
        if isinstance(message_payload, dict):
            message_id = message_payload.get("messageId") or message_payload.get("message_id")
        message_id = message_id or body.get("message_id") or body.get("messageId")

        if not message:
            return JSONResponse(status_code=400, content={"error": "Message is required"})
        if not message_id:
            return JSONResponse(status_code=400, content={"error": "message_id is required"})

        logger.info(f"Processing local chat request: {message[:50]}...")
        request_time_epoch = int(time.time() * 1000)
        result = await chat_service.process_message_async(
            message=message,
            session_id=session_id,
            request_time_epoch=request_time_epoch,
            message_id=message_id,
        )
        response_text = result.get("response_text", "")
        used_chunks = result.get("used_chunks", [])
        message_id = result.get("message_id")
        return build_chat_response(
            session_id=session_id,
            response_text=response_text,
            used_chunks=used_chunks,
            request_time_epoch=request_time_epoch,
            message_id=message_id,
        )

    except Exception as e:
        logger.exception("Error in local chat handler")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@app.post("/api/chat/sync")
def chat_sync(body: dict):
    """Handle chat requests using the synchronous process_message path.

    This endpoint mirrors the orchestrator controller flow for local testing.
    """
    if not chat_service:
        raise HTTPException(status_code=500, detail="ChatService not initialized")

    session_id = "local-session"
    try:
        message = extract_message_text(body)
        session_id = body.get("conversationId", body.get("conversation_id", "local-session")) or "local-session"
        user_id = body.get("user_id")
        message_id = None
        message_payload = body.get("message")
        if isinstance(message_payload, dict):
            message_id = message_payload.get("messageId") or message_payload.get("message_id")
        message_id = message_id or body.get("message_id") or body.get("messageId")

        if not session_id and user_id:
            session_id = user_id
        if not message:
            return JSONResponse(status_code=400, content={"error": "Message is required"})
        if not message_id:
            return JSONResponse(status_code=400, content={"error": "message_id is required"})

        logger.info(f"Processing local chat request (sync): {message[:50]}...")
        request_time_epoch = int(time.time() * 1000)
        result = chat_service.process_message(
            message,
            session_id,
            request_time_epoch,
            message_id,
        )
        response_text = result.get("response_text", "")
        used_chunks = result.get("used_chunks", [])
        message_id = result.get("message_id")
        return build_chat_response(
            session_id=session_id,
            response_text=response_text,
            used_chunks=used_chunks,
            request_time_epoch=request_time_epoch,
            message_id=message_id,
        )

    except ValueError as e:
        logger.warning("Validation error in local sync chat handler", extra={"error": str(e)})
        return JSONResponse(status_code=400, content={"error": sanitize_error_message(str(e), session_id)})

    except Exception as e:
        logger.exception("Error in local sync chat handler")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@app.put("/api/chat/{session_id}/feedback")
async def feedback(session_id: str, request: Request):
    """Handle feedback requests compatible with the Lambda handler."""
    if not chat_service:
        raise HTTPException(status_code=500, detail="ChatService not initialized")

    try:
        raw_body = await request.body()
        if not raw_body:
            return JSONResponse(status_code=400, content={"error": "Empty request body"})
        body = json.loads(raw_body)
        message_id = body.get("message_id") or body.get("messageId")
        feedback_data = body.get("feedback")
        if feedback_data is None:
            feedback_data = {key: value for key, value in body.items() if key not in {"message_id", "messageId"}}

        if not message_id:
            return JSONResponse(status_code=400, content={"error": "message_id is required"})
        if not feedback_data:
            return JSONResponse(status_code=400, content={"error": "feedback is required"})

        success = chat_service.store_feedback(session_id, message_id, feedback_data)
        return {"success": success}
    except Exception as e:
        logger.exception("Error in local feedback handler")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@app.get("/api/analytics")
async def analytics(request: Request):
    """Handle analytics requests for local dev."""
    from backend_orchestrator.services.analytics_service import AnalyticsService

    service = AnalyticsService()
    from_ts = request.query_params.get("from_ts")
    to_ts = request.query_params.get("to_ts")
    result = service.get_analytics(
        from_ts=int(from_ts) if from_ts else None,
        to_ts=int(to_ts) if to_ts else None,
    )
    return result.model_dump(by_alias=True)


@app.get("/api/analytics/documents")
async def analytics_documents():
    """Handle document inventory requests for local dev."""
    from backend_orchestrator.services.documents_service import get_documents

    result = get_documents()
    return result.model_dump(by_alias=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("mock.local_dev:app", host="127.0.0.1", port=8000, reload=True)
