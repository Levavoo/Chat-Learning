"""Health check Lambda handler: verifies DynamoDB, Bedrock, and KB connectivity."""

import json
import os
import time
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from botocore.config import Config
from botocore.exceptions import ClientError

logger = Logger()

HEALTH_CHECK_TIMEOUT = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 0})


def _check_dynamodb() -> dict[str, Any]:
    """Verify DynamoDB table is accessible via GetItem on a non-existent key."""
    table_name = os.getenv("DYNAMODB_TABLE_NAME", "")
    if not table_name:
        return {"status": "skipped", "reason": "DYNAMODB_TABLE_NAME not configured"}

    region = os.getenv("REGION", os.getenv("AWS_REGION", "eu-central-1"))
    start = time.time()
    try:
        client = boto3.client("dynamodb", region_name=region, config=HEALTH_CHECK_TIMEOUT)
        client.get_item(
            TableName=table_name,
            Key={
                "session_id": {"S": "__health_check_probe__"},
                "message_id": {"S": "__health_check_probe__"},
            },
            ProjectionExpression="session_id",
        )
        latency_ms = round((time.time() - start) * 1000)
    except (ClientError, Exception) as e:
        latency_ms = round((time.time() - start) * 1000)
        return {"status": "unhealthy", "latency_ms": latency_ms, "error": str(e)}
    else:
        return {"status": "healthy", "latency_ms": latency_ms}


def _check_bedrock() -> dict[str, Any]:
    """Verify Bedrock control plane is reachable via GetFoundationModel."""
    region = os.getenv("REGION", os.getenv("AWS_REGION", "eu-central-1"))
    model_id = os.getenv("BEDROCK_MODEL_ID", "")
    start = time.time()
    try:
        control_client = boto3.client("bedrock", region_name=region, config=HEALTH_CHECK_TIMEOUT)
        if model_id:
            control_client.get_foundation_model(modelIdentifier=model_id)
        else:
            control_client.list_foundation_models(byOutputModality="TEXT")
        latency_ms = round((time.time() - start) * 1000)
    except (ClientError, Exception) as e:
        latency_ms = round((time.time() - start) * 1000)
        # AccessDenied means missing diagnostic permission, not Bedrock being down.
        if isinstance(e, ClientError) and e.response.get("Error", {}).get("Code") == "AccessDeniedException":
            return {"status": "degraded", "latency_ms": latency_ms, "reason": "diagnostic permission missing"}
        return {"status": "unhealthy", "latency_ms": latency_ms, "error": str(e)}
    else:
        return {"status": "healthy", "latency_ms": latency_ms}


def _check_knowledge_base() -> dict[str, Any]:
    """Verify Bedrock Knowledge Base is accessible."""
    kb_id = os.getenv("KNOWLEDGE_BASE_ID", "")
    if not kb_id:
        return {"status": "skipped", "reason": "KNOWLEDGE_BASE_ID not configured"}

    region = os.getenv("REGION", os.getenv("AWS_REGION", "eu-central-1"))
    start = time.time()
    try:
        client = boto3.client("bedrock-agent", region_name=region, config=HEALTH_CHECK_TIMEOUT)
        response = client.get_knowledge_base(knowledgeBaseId=kb_id)
        kb_status = response["knowledgeBase"]["status"]
        latency_ms = round((time.time() - start) * 1000)
    except (ClientError, Exception) as e:
        latency_ms = round((time.time() - start) * 1000)
        return {"status": "unhealthy", "latency_ms": latency_ms, "error": str(e)}
    else:
        if kb_status == "ACTIVE":
            return {"status": "healthy", "latency_ms": latency_ms, "kb_status": kb_status}
        return {"status": "degraded", "latency_ms": latency_ms, "kb_status": kb_status}


@logger.inject_lambda_context
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for extended health check endpoint.

    Returns "healthy" only if all critical dependencies pass.
    """
    logger.info("Health check requested")

    checks = {
        "dynamodb": _check_dynamodb(),
        "bedrock": _check_bedrock(),
        "knowledge_base": _check_knowledge_base(),
    }

    statuses = [c["status"] for c in checks.values()]
    if all(s in ("healthy", "skipped") for s in statuses):
        overall = "healthy"
    elif any(s == "unhealthy" for s in statuses):
        overall = "unhealthy"
    else:
        overall = "degraded"

    region = os.getenv("REGION", os.getenv("AWS_REGION", "eu-central-1"))
    environment = os.getenv("ENVIRONMENT", "unknown")

    health_status = {
        "status": overall,
        "service": "chatbot-backend",
        "environment": environment,
        "region": region,
        "checks": checks,
    }

    status_code = 200 if overall == "healthy" else 503

    logger.info("Health check completed", extra={"status": overall, "checks": checks})

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
        "body": json.dumps(health_status),
    }
