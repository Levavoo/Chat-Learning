"""Lambda handler for analytics endpoints."""

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver, CORSConfig

from backend_orchestrator.config import get_config
from backend_orchestrator.controllers.analytics_controller import AnalyticsController

logger = Logger()
tracer = Tracer()

config = get_config()

cors_config = CORSConfig(
    allow_origin=config.allowed_origin,
    max_age=config.cors_max_age,
    allow_credentials=True,
)

app = APIGatewayRestResolver(cors=cors_config)
controller = AnalyticsController()


@app.get("/api/analytics")
@tracer.capture_method
def analytics_handler():
    """Return aggregated analytics for the editorial dashboard."""
    return controller.handle_analytics_request(app)


@app.get("/api/analytics/documents")
@tracer.capture_method
def documents_handler():
    """Return document inventory for the editorial dashboard."""
    return controller.handle_documents_request(app)


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event, context):
    """Lambda entry-point for analytics endpoints."""
    return app.resolve(event, context)
