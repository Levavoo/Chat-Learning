"""Tests for health Lambda handler.

boto3 is mocked because the CI runner role lacks Bedrock/DynamoDB
permissions; real integration runs in review environments.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend_orchestrator.health import lambda_handler

MOCK_CONTEXT = SimpleNamespace(
    function_name="renate-health-test",
    memory_limit_in_mb="256",
    invoked_function_arn="arn:aws:lambda:eu-central-1:123456789012:function:renate-health-test",
    aws_request_id="test-request-id",
)


def _mock_healthy_clients(service, **kwargs):
    client = MagicMock()
    if service == "dynamodb":
        client.get_item.return_value = {"Item": None}
    elif service == "bedrock-runtime":
        pass
    elif service == "bedrock":
        client.get_foundation_model.return_value = {"modelDetails": {"modelId": "test"}}
        client.list_foundation_models.return_value = {"modelSummaries": []}
    elif service == "bedrock-agent":
        client.get_knowledge_base.return_value = {"knowledgeBase": {"status": "ACTIVE"}}
    return client


@pytest.mark.unit
@patch("backend_orchestrator.health.boto3.client", side_effect=_mock_healthy_clients)
def test_health_returns_200(mock_client, monkeypatch):
    monkeypatch.setenv("DYNAMODB_TABLE_NAME", "renate-conversations-dev")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test-kb-id")
    response = lambda_handler({}, MOCK_CONTEXT)
    assert response["statusCode"] == 200


@pytest.mark.unit
@patch("backend_orchestrator.health.boto3.client", side_effect=_mock_healthy_clients)
def test_health_body_is_json_string(mock_client, monkeypatch):
    monkeypatch.setenv("DYNAMODB_TABLE_NAME", "renate-conversations-dev")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test-kb-id")
    response = lambda_handler({}, MOCK_CONTEXT)
    assert isinstance(response["body"], str), "body must be a JSON string for API Gateway proxy integration"
    body = json.loads(response["body"])
    assert body["status"] == "healthy"
