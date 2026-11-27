from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

logger = logging.getLogger(__name__)

# Pattern to match ${VAR_NAME}
ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


class MissingEnvironmentVariableError(Exception):
    """Raised when a required environment variable is not set."""

    def __init__(self, var_name: str) -> None:
        self.var_name = var_name
        super().__init__(f"Environment variable '{var_name}' is not set")


def _resolve_env_vars(value: Any, *, strict: bool = True) -> Any:
    """Recursively resolve ${VAR_NAME} patterns in config values."""
    if isinstance(value, str):

        def replace_env(match: re.Match) -> str:
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is not None:
                return env_value
            if strict:
                raise MissingEnvironmentVariableError(var_name)
            logger.warning("Environment variable '%s' is not set, keeping placeholder", var_name)
            return match.group(0)

        return ENV_VAR_PATTERN.sub(replace_env, value)
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v, strict=strict) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(item, strict=strict) for item in value]
    return value


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """Settings source that loads configuration from a config.yaml file.

    Path is from ``CONFIG_PATH`` or ``./config.yaml`` by default. ``${VAR_NAME}``
    substitution is supported.
    """

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        with Path(os.environ.get("CONFIG_PATH", "./config.yaml")).open() as config_text:
            config_yaml = yaml.safe_load(config_text)
            field_value = config_yaml.get(field_name, None)
            field_value = _resolve_env_vars(field_value)

        return field_value, field_name, False

    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        return value

    def __call__(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for field_name, field in self.settings_cls.model_fields.items():
            field_value, field_key, value_is_complex = self.get_field_value(field, field_name)
            field_value = self.prepare_field_value(field_name, field, field_value, value_is_complex)
            if field_value is not None:
                d[field_key] = field_value
        return d


class PipelineConfiguration(BaseSettings):
    """Pipeline configuration loaded from YAML."""

    repositories: dict[str, dict] = Field()
    pipelines: dict[str, dict] = Field()
    routes: dict[str, dict] = Field()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customize settings sources to include YAML configuration."""
        return (
            init_settings,
            YamlConfigSettingsSource(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
