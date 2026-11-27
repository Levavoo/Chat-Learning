"""Pytest configuration and fixtures."""

from unittest.mock import patch

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks tests as integration tests (require AWS credentials)")


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require AWS credentials",
    )


@pytest.fixture
def no_dynamodb_history():
    """Return an empty history instead of querying DynamoDB.

    Since #992 a failed history read rejects the request (fail-closed). Tests that run the real
    ChatService would otherwise depend on the machine: the CI runner role gets AccessDenied on
    the test table and answers 503, a laptop without AWS access disables the store and passes.
    """
    from backend_orchestrator.repositories.conversation import ConversationStore

    with patch.object(ConversationStore, "get_history", return_value=[]):
        yield
