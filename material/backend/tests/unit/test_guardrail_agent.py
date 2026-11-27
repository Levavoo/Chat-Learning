from unittest.mock import MagicMock, patch

import pytest

from backend_orchestrator.validators.guardrail_agent import (
    GuardrailCategory,
    _parse_classification,
    classify_user_input,
)

pytestmark = pytest.mark.unit


class TestParseClassification:
    def test_valid_json(self):
        result = _parse_classification('{"category": "BLOCK_STANDARD_1", "reason": "Off-topic"}')
        assert result.category == GuardrailCategory.BLOCK_STANDARD_1
        assert result.reason == "Off-topic"

    def test_json_with_surrounding_text(self):
        result = _parse_classification('Here is my answer: {"category": "ALLOW", "reason": "DRV-Thema"} done.')
        assert result.category == GuardrailCategory.ALLOW

    def test_no_json_defaults_to_allow(self):
        result = _parse_classification("I cannot classify this input")
        assert result.category == GuardrailCategory.ALLOW
        assert "fail open" in result.reason

    def test_invalid_json_defaults_to_allow(self):
        result = _parse_classification("{category: broken}")
        assert result.category == GuardrailCategory.ALLOW

    def test_unknown_category_defaults_to_block(self):
        result = _parse_classification('{"category": "UNKNOWN_THING", "reason": "test"}')
        assert result.category == GuardrailCategory.BLOCK_STANDARD_1

    def test_all_valid_categories(self):
        for cat in GuardrailCategory:
            result = _parse_classification(f'{{"category": "{cat.value}", "reason": "test"}}')
            assert result.category == cat

    def test_closing_brace_in_reason_does_not_truncate(self):
        r"""Regression: the old `\{[^}]+\}` regex stopped at the first '}', so a BLOCK with a
        brace in its reason yielded malformed JSON and silently downgraded to ALLOW."""
        result = _parse_classification('{"category": "BLOCK_STANDARD_1", "reason": "Zeichen } im Text"}')
        assert result.category == GuardrailCategory.BLOCK_STANDARD_1
        assert "}" in result.reason

    def test_json_in_code_fence(self):
        result = _parse_classification('```json\n{"category": "ALLOW", "reason": "ok"}\n```')
        assert result.category == GuardrailCategory.ALLOW
        assert result.reason == "ok"


class TestClassifyUserInput:
    @patch("backend_orchestrator.validators.guardrail_agent._get_bedrock_client")
    @patch("backend_orchestrator.validators.guardrail_agent.get_config")
    def test_successful_classification(self, mock_config, mock_client):
        config = MagicMock()
        config.aws_region = "eu-central-1"
        config.guardrail_agent_model_id = "eu.amazon.nova-lite-v1:0"
        mock_config.return_value = config

        client = MagicMock()
        mock_client.return_value = client
        client.converse.return_value = {
            "output": {"message": {"content": [{"text": '{"category": "BLOCK_STANDARD_1", "reason": "Off-topic"}'}]}}
        }

        result = classify_user_input("Wie kaufe ich Bitcoin?")

        assert result.category == GuardrailCategory.BLOCK_STANDARD_1
        assert result.reason == "Off-topic"

    @patch("backend_orchestrator.validators.guardrail_agent._get_bedrock_client")
    @patch("backend_orchestrator.validators.guardrail_agent.get_config")
    def test_conversation_context_included_in_prompt(self, mock_config, mock_client):
        config = MagicMock()
        config.aws_region = "eu-central-1"
        config.guardrail_agent_model_id = "eu.amazon.nova-lite-v1:0"
        mock_config.return_value = config

        client = MagicMock()
        mock_client.return_value = client
        client.converse.return_value = {
            "output": {"message": {"content": [{"text": '{"category": "ALLOW", "reason": "Folgefrage"}'}]}}
        }

        result = classify_user_input(
            "und wenn ich Lehrer bin?",
            conversation_context="Nutzer: Kann ich mit 60 in Rente gehen?\nRenate: Nur in Ausnahmefällen.",
        )

        assert result.category == GuardrailCategory.ALLOW
        sent_text = client.converse.call_args[1]["messages"][0]["content"][0]["text"]
        assert "Bisheriger Gesprächsverlauf:" in sent_text
        assert "Kann ich mit 60 in Rente gehen?" in sent_text
        assert "Aktuelle Nutzereingabe (zu klassifizieren):\nund wenn ich Lehrer bin?" in sent_text

    @patch("backend_orchestrator.validators.guardrail_agent._get_bedrock_client")
    @patch("backend_orchestrator.validators.guardrail_agent.get_config")
    def test_no_context_sends_plain_message(self, mock_config, mock_client):
        config = MagicMock()
        config.aws_region = "eu-central-1"
        config.guardrail_agent_model_id = "eu.amazon.nova-lite-v1:0"
        mock_config.return_value = config

        client = MagicMock()
        mock_client.return_value = client
        client.converse.return_value = {
            "output": {"message": {"content": [{"text": '{"category": "ALLOW", "reason": "ok"}'}]}}
        }

        classify_user_input("Wann kann ich in Rente gehen?")

        sent_text = client.converse.call_args[1]["messages"][0]["content"][0]["text"]
        assert sent_text == "Wann kann ich in Rente gehen?"

    @patch("backend_orchestrator.validators.guardrail_agent._get_bedrock_client")
    @patch("backend_orchestrator.validators.guardrail_agent.get_config")
    def test_api_error_defaults_to_block(self, mock_config, mock_client):
        """Non-transient API errors must fail closed (BLOCK_STANDARD_1)."""
        config = MagicMock()
        config.aws_region = "eu-central-1"
        config.guardrail_agent_model_id = "eu.amazon.nova-lite-v1:0"
        mock_config.return_value = config

        client = MagicMock()
        mock_client.return_value = client
        client.converse.side_effect = Exception("Service unavailable")

        result = classify_user_input("Some question")

        assert result.category == GuardrailCategory.BLOCK_STANDARD_1
        assert "fail closed" in result.reason

    @patch("backend_orchestrator.validators.guardrail_agent._get_bedrock_client")
    @patch("backend_orchestrator.validators.guardrail_agent.get_config")
    def test_malformed_response_defaults_to_allow(self, mock_config, mock_client):
        config = MagicMock()
        config.aws_region = "eu-central-1"
        config.guardrail_agent_model_id = "eu.amazon.nova-lite-v1:0"
        mock_config.return_value = config

        client = MagicMock()
        mock_client.return_value = client
        client.converse.return_value = {"output": {"message": {"content": [{"text": "I don't know what to say"}]}}}

        result = classify_user_input("Some question")

        assert result.category == GuardrailCategory.ALLOW
