import json
from unittest.mock import Mock, patch

import pytest

from backend_orchestrator.health import lambda_handler as health_handler
from backend_orchestrator.orchestrator import lambda_handler as chat_handler

pytestmark = pytest.mark.usefixtures("no_dynamodb_history")


class TestHandler:
    def mock_context(self):
        context = Mock()
        context.function_name = "test-function"
        context.memory_limit_in_mb = 128
        context.invoked_function_arn = "arn:aws:lambda:eu-central-1:123456789012:function:test-function"
        context.aws_request_id = "test-request-id"
        return context

    @patch("backend_orchestrator.services.chat_service.run_agent")
    def test_chat_handler_success(self, mock_run_agent):
        mock_result = Mock()
        mock_result.result = "Hello from Renate!"
        mock_result.sources = []
        mock_result.all_sources = []
        mock_result.tool_calls = []
        mock_run_agent.return_value = mock_result

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

        response = chat_handler(event, self.mock_context())

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["conversationId"] == "test123"
        assert body["message"]["content"][0]["body"] == "Hello from Renate!"

    @patch("backend_orchestrator.services.chat_service.run_agent")
    def test_chat_handler_missing_message(self, mock_run_agent):
        event = {
            "httpMethod": "POST",
            "path": "/api/chat",
            "body": json.dumps({"conversation_id": "test123", "message_id": "test123#uuid"}),
            "requestContext": {
                "requestTimeEpoch": 1700000000000,
                "path": "/api/chat",
            },
        }

        response = chat_handler(event, self.mock_context())
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "error" in body

    @patch("backend_orchestrator.health.boto3.client")
    def test_health_handler_success(self, mock_boto_client):
        mock_client = Mock()
        mock_client.get_item.return_value = {"Item": None}
        mock_client.get_foundation_model.return_value = {"modelDetails": {"modelId": "test"}}
        mock_client.list_foundation_models.return_value = {"modelSummaries": []}
        mock_client.get_knowledge_base.return_value = {"knowledgeBase": {"status": "ACTIVE"}}
        mock_boto_client.return_value = mock_client

        event = {}
        response = health_handler(event, self.mock_context())

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "healthy"
        assert body["service"] == "chatbot-backend"

    @patch("backend_orchestrator.retrieval_diagnostic.run_retrieval_diagnostic")
    def test_chat_handler_routes_qa_retrieval_promotion_source(self, mock_diagnostic):
        mock_diagnostic.return_value = {"ok": True}
        event = {"source": "qa-retrieval-promotion", "mode": "semantic", "query": "test"}

        response = chat_handler(event, self.mock_context())

        assert response == {"ok": True}
        mock_diagnostic.assert_called_once_with(event)

    @patch("backend_orchestrator.retrieval_diagnostic.run_retrieval_diagnostic")
    def test_chat_handler_routes_qa_retrieval_rollback_source(self, mock_diagnostic):
        """Regression: routing must recognize "qa-retrieval-rollback" (#493), not only "-promotion"."""
        mock_diagnostic.return_value = {"ok": True}
        event = {"source": "qa-retrieval-rollback", "mode": "hybrid", "query": "test"}

        response = chat_handler(event, self.mock_context())

        assert response == {"ok": True}
        mock_diagnostic.assert_called_once_with(event)

    @patch("backend_orchestrator.retrieval_diagnostic.run_retrieval_diagnostic")
    def test_chat_handler_routes_qa_retrieval_monitoring_source(self, mock_diagnostic):
        """Scheduled health check (#494) must bypass the API Gateway resolver."""
        mock_diagnostic.return_value = {"ok": True}
        event = {"source": "qa-retrieval-monitoring", "mode": "hybrid", "query": "test"}

        response = chat_handler(event, self.mock_context())

        assert response == {"ok": True}
        mock_diagnostic.assert_called_once_with(event)

    @patch("backend_orchestrator.retrieval_diagnostic.run_retrieval_diagnostic")
    def test_chat_handler_routes_preprod_retrieval_sources(self, mock_diagnostic):
        mock_diagnostic.return_value = {"ok": True}
        event = {
            "source": "preprod-retrieval-promotion",
            "mode": "hybrid",
            "query": "test",
        }

        response = chat_handler(event, self.mock_context())

        assert response == {"ok": True}
        mock_diagnostic.assert_called_once_with(event)

    @patch("backend_orchestrator.retrieval_diagnostic.run_retrieval_diagnostic")
    def test_chat_handler_routes_prod_retrieval_sources(self, mock_diagnostic):
        mock_diagnostic.return_value = {"ok": True}
        event = {
            "source": "prod-retrieval-promotion",
            "mode": "hybrid",
            "query": "test",
        }

        response = chat_handler(event, self.mock_context())

        assert response == {"ok": True}
        mock_diagnostic.assert_called_once_with(event)

    def test_chat_handler_rejects_unrecognized_diagnostic_source(self):
        """An unrelated 'source' value must resolve as a normal API Gateway event."""
        event = {"source": "some-other-caller", "httpMethod": "GET", "path": "/health"}

        response = chat_handler(event, self.mock_context())

        assert "ok" not in response
