"""Controller for DSFA consent logging."""

import contextlib
import json
import os
from datetime import UTC, datetime
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver

logger = Logger(child=True)

CONSENT_LOG_GROUP = os.environ.get("CONSENT_LOG_GROUP", "")


class ConsentController:
    """Handles consent logging to a dedicated CloudWatch log group."""

    def __init__(self, log_group_name: str | None = None, logs_client=None):
        """Initialize with optional overrides for testing."""
        self.log_group_name = log_group_name or CONSENT_LOG_GROUP
        self._logs_client = logs_client

    @property
    def logs_client(self):
        """Lazy-init boto3 CloudWatch Logs client."""
        if self._logs_client is None:
            self._logs_client = boto3.client("logs")
        return self._logs_client

    def handle_consent_request(self, app: APIGatewayRestResolver) -> dict[str, Any]:
        """Log consent event and return 200.

        Always returns {"status": "ok"} — errors are logged internally but
        never surfaced to the client (best-effort).
        """
        try:
            ip = "unknown"
            with contextlib.suppress(AttributeError, TypeError):
                ip = app.current_event.request_context.identity.source_ip or "unknown"

            session_id: str | None = None
            with contextlib.suppress(Exception):
                body = app.current_event.json_body
                if isinstance(body, dict):
                    session_id = body.get("sessionId")

            timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
            stream_name = f"consent/{date_str}"

            log_data: dict[str, Any] = {"ip": ip, "timestamp": timestamp, "consent": True, "service": "consent"}
            if session_id:
                log_data["sessionId"] = session_id

            log_entry = json.dumps(log_data)

            with contextlib.suppress(self.logs_client.exceptions.ResourceAlreadyExistsException):
                self.logs_client.create_log_stream(
                    logGroupName=self.log_group_name,
                    logStreamName=stream_name,
                )

            self.logs_client.put_log_events(
                logGroupName=self.log_group_name,
                logStreamName=stream_name,
                logEvents=[{"timestamp": int(datetime.now(tz=UTC).timestamp() * 1000), "message": log_entry}],
            )

        except Exception:
            logger.exception("Failed to write consent log entry")

        return {"status": "ok"}
