from unittest.mock import MagicMock, patch

import pytest

from backend_orchestrator.health import lambda_handler


@pytest.fixture
def _env_vars(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("REGION", "eu-central-1")
    monkeypatch.setenv("DYNAMODB_TABLE_NAME", "renate-conversations-dev")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "ABCDEF1234")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "openai.gpt-oss-120b-1:0")


@pytest.fixture
def api_gw_event():
    return {"httpMethod": "GET", "path": "/health"}


@pytest.mark.usefixtures("_env_vars")
class TestHealthCheckAllHealthy:
    @patch("backend_orchestrator.health.boto3.client")
    def test_returns_200_when_all_healthy(self, mock_boto_client, api_gw_event):
        dynamo_client = MagicMock()
        dynamo_client.get_item.return_value = {"Item": None}

        bedrock_client = MagicMock()
        bedrock_client.get_foundation_model.return_value = {"modelDetails": {"modelId": "test"}}

        agent_client = MagicMock()
        agent_client.get_knowledge_base.return_value = {"knowledgeBase": {"status": "ACTIVE"}}

        def client_factory(service, **kwargs):
            if service == "dynamodb":
                return dynamo_client
            if service == "bedrock":
                return bedrock_client
            if service == "bedrock-agent":
                return agent_client
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        response = lambda_handler(api_gw_event, MagicMock())

        assert response["statusCode"] == 200
        import json

        body = json.loads(response["body"])
        assert body["status"] == "healthy"
        assert body["checks"]["dynamodb"]["status"] == "healthy"
        assert body["checks"]["bedrock"]["status"] == "healthy"
        assert body["checks"]["knowledge_base"]["status"] == "healthy"


@pytest.mark.usefixtures("_env_vars")
class TestHealthCheckDynamoDBFailure:
    @patch("backend_orchestrator.health.boto3.client")
    def test_returns_503_when_dynamodb_unhealthy(self, mock_boto_client, api_gw_event):
        from botocore.exceptions import ClientError

        dynamo_client = MagicMock()
        dynamo_client.get_item.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Table not found"}},
            "DescribeTable",
        )

        bedrock_client = MagicMock()
        bedrock_client.get_foundation_model.return_value = {"modelDetails": {"modelId": "test"}}

        agent_client = MagicMock()
        agent_client.get_knowledge_base.return_value = {"knowledgeBase": {"status": "ACTIVE"}}

        def client_factory(service, **kwargs):
            if service == "dynamodb":
                return dynamo_client
            if service == "bedrock":
                return bedrock_client
            if service == "bedrock-agent":
                return agent_client
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        response = lambda_handler(api_gw_event, MagicMock())

        assert response["statusCode"] == 503
        import json

        body = json.loads(response["body"])
        assert body["status"] == "unhealthy"
        assert body["checks"]["dynamodb"]["status"] == "unhealthy"
        assert "error" in body["checks"]["dynamodb"]


@pytest.mark.usefixtures("_env_vars")
class TestHealthCheckBedrockFailure:
    @patch("backend_orchestrator.health.boto3.client")
    def test_returns_503_when_bedrock_unhealthy(self, mock_boto_client, api_gw_event):
        dynamo_client = MagicMock()
        dynamo_client.get_item.return_value = {"Item": None}

        bedrock_client = MagicMock()
        bedrock_client.get_foundation_model.side_effect = Exception("Connection timeout")

        agent_client = MagicMock()
        agent_client.get_knowledge_base.return_value = {"knowledgeBase": {"status": "ACTIVE"}}

        def client_factory(service, **kwargs):
            if service == "dynamodb":
                return dynamo_client
            if service == "bedrock":
                return bedrock_client
            if service == "bedrock-agent":
                return agent_client
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        response = lambda_handler(api_gw_event, MagicMock())

        assert response["statusCode"] == 503
        import json

        body = json.loads(response["body"])
        assert body["status"] == "unhealthy"
        assert body["checks"]["bedrock"]["status"] == "unhealthy"


class TestHealthCheckMissingConfig:
    @patch("backend_orchestrator.health.boto3.client")
    def test_skips_dynamodb_when_table_not_configured(self, mock_boto_client, api_gw_event, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("REGION", "eu-central-1")
        monkeypatch.setenv("DYNAMODB_TABLE_NAME", "")
        monkeypatch.setenv("KNOWLEDGE_BASE_ID", "")
        monkeypatch.setenv("BEDROCK_MODEL_ID", "")

        bedrock_client = MagicMock()
        bedrock_client.get_foundation_model.return_value = {"modelDetails": {"modelId": "test"}}

        mock_boto_client.return_value = bedrock_client

        response = lambda_handler(api_gw_event, MagicMock())

        assert response["statusCode"] == 200
        import json

        body = json.loads(response["body"])
        assert body["checks"]["dynamodb"]["status"] == "skipped"
        assert body["checks"]["knowledge_base"]["status"] == "skipped"
