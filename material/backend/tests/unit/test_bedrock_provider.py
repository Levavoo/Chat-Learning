"""Unit tests for bedrock_provider module."""

from unittest.mock import MagicMock, patch

import pytest

from backend_orchestrator.providers import bedrock_provider
from backend_orchestrator.providers.bedrock_provider import (
    create_bedrock_model,
    get_bedrock_model_settings,
    get_cached_provider,
)


class TestGetCachedProvider:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        bedrock_provider._provider_cache.clear()
        yield
        bedrock_provider._provider_cache.clear()

    @patch("backend_orchestrator.providers.bedrock_provider.BedrockProvider")
    def test_returns_distinct_provider_per_region(self, mock_provider_cls):
        """Different regions must yield different providers (regression: REN-22)."""
        mock_provider_cls.side_effect = lambda region_name: MagicMock(region=region_name)

        eu = get_cached_provider("eu-central-1")
        us = get_cached_provider("us-east-1")

        assert eu is not us
        assert mock_provider_cls.call_count == 2
        mock_provider_cls.assert_any_call(region_name="eu-central-1")
        mock_provider_cls.assert_any_call(region_name="us-east-1")
        assert "eu-central-1" in bedrock_provider._provider_cache
        assert "us-east-1" in bedrock_provider._provider_cache

    @patch("backend_orchestrator.providers.bedrock_provider.BedrockProvider")
    def test_caches_provider_per_region(self, mock_provider_cls):
        mock_provider_cls.return_value = MagicMock()

        first = get_cached_provider("eu-central-1")
        second = get_cached_provider("eu-central-1")

        assert first is second
        assert mock_provider_cls.call_count == 1


class TestCreateBedrockModel:
    @patch("backend_orchestrator.providers.bedrock_provider.get_cached_provider")
    @patch("backend_orchestrator.providers.bedrock_provider.BedrockConverseModel")
    def test_create_bedrock_model(self, mock_model_cls, mock_get_cached_provider):
        mock_provider = MagicMock()
        mock_get_cached_provider.return_value = mock_provider

        create_bedrock_model("test-model-id")

        mock_get_cached_provider.assert_called_with("eu-central-1")
        mock_model_cls.assert_called_with(
            model_name="test-model-id",
            provider=mock_provider,
        )

    @patch("backend_orchestrator.providers.bedrock_provider.get_cached_provider")
    @patch("backend_orchestrator.providers.bedrock_provider.BedrockConverseModel")
    def test_create_bedrock_model_custom_region(self, mock_model_cls, mock_get_cached_provider):
        mock_provider = MagicMock()
        mock_get_cached_provider.return_value = mock_provider

        create_bedrock_model("test-model-id", region="us-west-2")

        mock_get_cached_provider.assert_called_with("us-west-2")


class TestGetBedrockModelSettings:
    @patch("backend_orchestrator.providers.bedrock_provider.get_config")
    def test_settings_without_guardrail(self, mock_get_config):
        """Guardrails are applied at input validation level, not in model settings."""
        config = MagicMock()
        config.bedrock_temperature = None
        config.bedrock_top_p = None
        mock_get_config.return_value = config

        settings = get_bedrock_model_settings()

        assert settings.get("bedrock_guardrail_config") is None
        assert settings.get("bedrock_cache_instructions") is None
        assert settings.get("bedrock_cache_messages") is None

    @patch("backend_orchestrator.providers.bedrock_provider.get_config")
    def test_settings_cache_disabled(self, mock_get_config):
        """Nova models don't support cachePoint."""
        config = MagicMock()
        config.bedrock_temperature = None
        config.bedrock_top_p = None
        mock_get_config.return_value = config

        settings = get_bedrock_model_settings()

        assert settings.get("bedrock_cache_instructions") is None
        assert settings.get("bedrock_cache_messages") is None

    @patch("backend_orchestrator.providers.bedrock_provider.get_config")
    def test_settings_with_temperature(self, mock_get_config):
        config = MagicMock()
        config.bedrock_temperature = None
        config.bedrock_top_p = None
        mock_get_config.return_value = config

        settings = get_bedrock_model_settings(temperature=0.7)

        assert settings.get("temperature") == 0.7

    @patch("backend_orchestrator.providers.bedrock_provider.get_config")
    def test_settings_with_top_p(self, mock_get_config):
        config = MagicMock()
        config.bedrock_temperature = None
        config.bedrock_top_p = None
        mock_get_config.return_value = config

        settings = get_bedrock_model_settings(top_p=0.9)

        assert settings.get("top_p") == 0.9
