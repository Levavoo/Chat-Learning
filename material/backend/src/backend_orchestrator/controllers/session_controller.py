"""Controller for session data deletion (Widerruf)."""

import re
from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.event_handler.exceptions import BadRequestError

from backend_orchestrator.repositories.conversation import ConversationStore
from backend_orchestrator.utils.session_masking import mask_session_id

logger = Logger(child=True)

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class SessionController:
    """Handles session data deletion for DSFA Widerruf compliance."""

    def __init__(self, conversation_store: ConversationStore):
        """Initialize with conversation store dependency."""
        self._conversation_store = conversation_store

    def handle_delete_session(self, app: APIGatewayRestResolver, conversation_id: str) -> dict[str, Any]:
        """Delete all conversation items for a session. Best-effort — always returns 200.

        Raises BadRequestError if conversation_id is not a valid UUID format.
        """
        if not UUID_PATTERN.match(conversation_id):
            raise BadRequestError("Invalid conversation ID format")

        try:
            deleted_count = self._conversation_store.delete_session(conversation_id)
            logger.info(
                "Session deleted",
                extra={"session_id": mask_session_id(conversation_id), "deleted_count": deleted_count},
            )
        except Exception:
            logger.exception(
                "Session deletion handler error",
                extra={"session_id": mask_session_id(conversation_id)},
            )

        return {"status": "ok"}
