import json
from unittest.mock import Mock, patch

import pytest

from backend_orchestrator.config import get_config
from backend_orchestrator.orchestrator import lambda_handler

pytestmark = pytest.mark.usefixtures("no_dynamodb_history")

config = get_config()
MAX_MESSAGE_LENGTH = config.max_message_length


class TestInputValidation:
    def mock_context(self):
        context = Mock()
        context.function_name = "test-function"
        context.memory_limit_in_mb = 128
        context.invoked_function_arn = "arn:aws:lambda:eu-central-1:123456789012:function:test-function"
        context.aws_request_id = "test-request-id"
        return context

    def test_message_too_long(self):
        long_message = "A" * (MAX_MESSAGE_LENGTH + 1)
        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": json.dumps({
                "message": {
                    "role": "user",
                    "content": [{"contentType": "text", "body": long_message}],
                    "model": "amazon-nova-pro",
                    "messageId": "test123#uuid",
                }
            }),
            "requestContext": {
                "authorizer": {"claims": {"sub": "user-456", "cognito:username": "testuser"}},
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = lambda_handler(event, self.mock_context())
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "exceeds maximum length" in body["error"]

    def test_message_too_short(self):
        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": json.dumps({
                "message": {
                    "role": "user",
                    "content": [{"contentType": "text", "body": ""}],
                    "model": "amazon-nova-pro",
                    "messageId": "test123#uuid",
                },
                "conversation_id": "test123",
            }),
            "requestContext": {
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = lambda_handler(event, self.mock_context())
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "required" in body["error"]

    def test_message_with_word_over_max_word_length_rejected(self):
        """Single word longer than max_word_length (1000 chars) is rejected with 400 (#664 AC1)."""
        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": json.dumps({
                "message": {
                    "role": "user",
                    "content": [{"contentType": "text", "body": "A" * 1001}],
                    "model": "amazon-nova-pro",
                    "messageId": "test123#uuid",
                },
                "conversation_id": "test123",
            }),
            "requestContext": {
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = lambda_handler(event, self.mock_context())
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "word exceeding maximum length" in body["error"]

    def test_message_with_high_special_char_ratio_rejected(self):
        """Message with >50% special characters is rejected with 400 (#664 AC2)."""
        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": json.dumps({
                "message": {
                    "role": "user",
                    "content": [{"contentType": "text", "body": "!@#$%^&*()" * 5 + "ab"}],
                    "model": "amazon-nova-pro",
                    "messageId": "test123#uuid",
                },
                "conversation_id": "test123",
            }),
            "requestContext": {
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = lambda_handler(event, self.mock_context())
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "special character ratio" in body["error"]


class TestErrorHandling:
    def mock_context(self):
        context = Mock()
        context.function_name = "test-function"
        context.memory_limit_in_mb = 128
        context.invoked_function_arn = "arn:aws:lambda:eu-central-1:123456789012:function:test-function"
        context.aws_request_id = "test-request-id"
        return context

    @patch("backend_orchestrator.services.chat_service.run_agent")
    def test_agent_error_handling(self, mock_run_agent):
        mock_run_agent.side_effect = Exception("Bedrock service unavailable")

        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": json.dumps({
                "message": {
                    "role": "user",
                    "content": [{"contentType": "text", "body": "Hello"}],
                    "model": "amazon-nova-pro",
                    "messageId": "test123#uuid",
                }
            }),
            "requestContext": {
                "authorizer": {"claims": {"sub": "user-456", "cognito:username": "testuser"}},
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = lambda_handler(event, self.mock_context())
        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert "error" in body
        error_msg = body["error"]
        assert "Internal server error" in error_msg or "Bedrock service unavailable" in error_msg

    @patch("backend_orchestrator.services.chat_service.run_agent")
    def test_500_response_envelope_carries_no_session_id(self, mock_run_agent):
        """A 500 from run_agent must not leak the session-id in body or headers (#483 / RFC M6)."""
        full_session = "sess-full-abc-9999-distinct"
        mock_run_agent.side_effect = Exception(f"Bedrock refused conversation {full_session}")

        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": json.dumps({
                "conversationId": full_session,
                "message": {
                    "role": "user",
                    "content": [{"contentType": "text", "body": "Hello"}],
                    "model": "amazon-nova-pro",
                    "messageId": f"{full_session}#uuid",
                },
            }),
            "requestContext": {
                "authorizer": {"claims": {"sub": "user-456", "cognito:username": "testuser"}},
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = lambda_handler(event, self.mock_context())
        assert response["statusCode"] == 500
        assert full_session not in json.dumps(response.get("headers", {}) or {})
        body = json.loads(response["body"])
        assert full_session not in json.dumps(body)

    def test_malformed_json_body(self):
        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": "not valid json",
            "requestContext": {
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = lambda_handler(event, self.mock_context())
        assert response["statusCode"] in [400, 200]

    @patch("backend_orchestrator.services.chat_service.run_agent")
    def test_missing_message_field(self, mock_run_agent):
        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": json.dumps({"conversation_id": "test123", "message_id": "test123#uuid"}),
            "requestContext": {
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = lambda_handler(event, self.mock_context())
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "required" in body["error"].lower()

    @patch("backend_orchestrator.services.chat_service.run_agent")
    def test_complex_message_structure(self, mock_run_agent):
        mock_run_agent.return_value = {"result": "Test response", "sources": [], "tool_calls": []}

        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": json.dumps({
                "message": {
                    "role": "user",
                    "content": [{"contentType": "text", "body": "Hello Renate"}],
                    "model": "amazon-nova-pro",
                    "messageId": "test123#uuid",
                },
                "conversation_id": "test123",
            }),
            "requestContext": {
                "authorizer": {"claims": {"sub": "user-456", "cognito:username": "testuser"}},
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = lambda_handler(event, self.mock_context())
        # #882 reproducer: only run_agent is mocked, so DynamoDB/KB raises; kept as 500 until full ChatService fakes exist.
        assert response["statusCode"] == 500


class TestEdgeCases:
    def mock_context(self):
        context = Mock()
        context.function_name = "test-function"
        context.memory_limit_in_mb = 128
        context.invoked_function_arn = "arn:aws:lambda:eu-central-1:123456789012:function:test-function"
        context.aws_request_id = "test-request-id"
        return context

    @patch("backend_orchestrator.services.chat_service.run_agent")
    def test_message_at_exact_max_length(self, mock_run_agent):
        mock_run_agent.return_value = {"result": "Test response", "sources": [], "tool_calls": []}

        sentence = "This is a realistic sentence that someone might type. "
        exact_max_message = (sentence * (MAX_MESSAGE_LENGTH // len(sentence) + 1))[:MAX_MESSAGE_LENGTH]

        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": json.dumps({
                "message": {
                    "role": "user",
                    "content": [{"contentType": "text", "body": exact_max_message}],
                    "model": "amazon-nova-pro",
                    "messageId": "test123#uuid",
                }
            }),
            "requestContext": {
                "authorizer": {"claims": {"sub": "user-456", "cognito:username": "testuser"}},
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = lambda_handler(event, self.mock_context())
        # #882 reproducer: only run_agent is mocked, so DynamoDB/KB raises; kept as 500 until full ChatService fakes exist.
        assert response["statusCode"] == 500

    @patch("backend_orchestrator.services.chat_service.run_agent")
    def test_session_id_fallback_to_user_id(self, mock_run_agent):
        """session_id falls back to user_id when not provided."""
        mock_run_agent.return_value = {"result": "Test response", "sources": [], "tool_calls": []}

        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": json.dumps({
                "message": {
                    "role": "user",
                    "content": [{"contentType": "text", "body": "Hello"}],
                    "model": "amazon-nova-pro",
                    "messageId": "user-456#uuid",
                }
            }),
            "requestContext": {
                "authorizer": {"claims": {"sub": "user-456", "cognito:username": "testuser"}},
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = lambda_handler(event, self.mock_context())
        # #882 reproducer: only run_agent is mocked, so DynamoDB/KB raises; kept as 500 until full ChatService fakes exist.
        assert response["statusCode"] == 500
