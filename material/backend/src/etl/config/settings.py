from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings

from etl.config.aws import AwsSettings
from etl.config.log_config import LoggingSettings
from etl.config.pipeline import PipelineConfiguration


class Settings(BaseSettings):
    """Application settings combining AWS, logging, and pipeline configurations."""

    aws: AwsSettings = Field(default_factory=AwsSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    pipeline_configuration: PipelineConfiguration = Field(default_factory=PipelineConfiguration)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the settings instance, creating it lazily on first access."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


class _SettingsProxy:
    """Proxy enabling lazy initialization while preserving ``settings.foo`` access."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_settings(), name)


settings = _SettingsProxy()
