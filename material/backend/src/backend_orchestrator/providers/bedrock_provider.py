"""Factory for creating AWS Bedrock providers and models."""

from aws_lambda_powertools import Logger
from pydantic_ai.models.bedrock import BedrockConverseModel, BedrockModelSettings
from pydantic_ai.providers.bedrock import BedrockProvider

from backend_orchestrator.config import get_config

logger = Logger(child=True)

_provider_cache: dict[str, BedrockProvider] = {}


def get_cached_provider(region: str) -> BedrockProvider:
    """Get or create cached BedrockProvider for region."""
    if region not in _provider_cache:
        _provider_cache[region] = BedrockProvider(region_name=region)
    return _provider_cache[region]


def get_bedrock_model_settings(
    temperature: float | None = None,
    top_p: float | None = None,
) -> BedrockModelSettings:
    """Create BedrockModelSettings without guardrails. Per-model overrides win over env defaults."""
    config = get_config()

    settings: dict = {}

    effective_temp = temperature if temperature is not None else config.bedrock_temperature
    effective_top_p = top_p if top_p is not None else config.bedrock_top_p
    if effective_temp is not None:
        settings["temperature"] = effective_temp
    if effective_top_p is not None:
        settings["top_p"] = effective_top_p

    return BedrockModelSettings(**settings)


def create_bedrock_model(model_id: str, region: str = "eu-central-1") -> BedrockConverseModel:
    """Create a Bedrock Converse model for pydantic-ai."""
    logger.info("Creating Bedrock model", extra={"model_id": model_id, "region": region})

    provider = get_cached_provider(region)

    return BedrockConverseModel(
        model_name=model_id,
        provider=provider,
    )
