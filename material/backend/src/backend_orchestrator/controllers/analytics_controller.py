"""Controller layer for analytics operations."""

from typing import Any

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.event_handler.exceptions import BadRequestError, InternalServerError

from backend_orchestrator.services.analytics_service import AnalyticsService

logger = Logger(child=True)
tracer = Tracer()


class AnalyticsController:
    """Controller for handling analytics API requests."""

    def __init__(self) -> None:
        self._service = AnalyticsService()

    @tracer.capture_method
    def handle_analytics_request(self, app: APIGatewayRestResolver) -> dict[str, Any]:
        """Handle analytics dashboard requests."""
        try:
            from_ts_raw = app.current_event.get_query_string_value("from_ts")
            to_ts_raw = app.current_event.get_query_string_value("to_ts")
            try:
                from_ts = int(from_ts_raw) if from_ts_raw is not None else None
                to_ts = int(to_ts_raw) if to_ts_raw is not None else None
            except ValueError:
                raise BadRequestError("from_ts and to_ts must be integers") from None
            result = self._service.get_analytics(from_ts=from_ts, to_ts=to_ts)
            return result.model_dump(by_alias=True)
        except (BadRequestError, InternalServerError):
            raise
        except Exception:
            logger.exception("Error processing analytics request")
            raise InternalServerError("Internal server error") from None

    @tracer.capture_method
    def handle_documents_request(self, app: APIGatewayRestResolver) -> dict[str, Any]:
        """Handle document inventory requests for the editorial dashboard."""
        try:
            from backend_orchestrator.services.documents_service import get_documents

            result = get_documents()
            return result.model_dump(by_alias=True)
        except Exception:
            logger.exception("Error processing documents request")
            raise InternalServerError("Internal server error") from None
