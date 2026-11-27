"""Tests for HyDE (Hypothetical Document Embeddings) module."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from backend_orchestrator.tools import hyde
from backend_orchestrator.tools.hyde import generate_hypothetical_document


class TestGenerateHypotheticalDocument:
    def setup_method(self):
        hyde._bedrock_runtime_client = None

    @patch("backend_orchestrator.tools.hyde.boto3")
    def test_returns_hypothetical_document(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Hypothetical DRV document text."}]}}
        }

        result = generate_hypothetical_document("Was ist Altersrente?", "model-id", "eu-central-1")

        assert result == "Hypothetical DRV document text."
        mock_client.converse.assert_called_once()

    @patch("backend_orchestrator.tools.hyde.boto3")
    def test_falls_back_on_empty_response(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.converse.return_value = {"output": {"message": {"content": []}}}

        result = generate_hypothetical_document("original query", "model-id", "eu-central-1")

        assert result == "original query"

    @patch("backend_orchestrator.tools.hyde.boto3")
    def test_falls_back_on_empty_text_block(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": "   "}]}}}

        result = generate_hypothetical_document("original query", "model-id", "eu-central-1")

        assert result == "original query"

    @patch("backend_orchestrator.tools.hyde.boto3")
    def test_falls_back_on_exception(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.converse.side_effect = Exception("Bedrock error")

        result = generate_hypothetical_document("original query", "model-id", "eu-central-1")

        assert result == "original query"

    @patch("backend_orchestrator.tools.hyde.boto3")
    def test_strips_whitespace_from_result(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": "  some doc  "}]}}}

        result = generate_hypothetical_document("query", "model-id", "eu-central-1")

        assert result == "some doc"

    @patch("backend_orchestrator.tools.hyde.boto3")
    def test_client_is_cached(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": "doc"}]}}}

        generate_hypothetical_document("q1", "model-id", "eu-central-1")
        generate_hypothetical_document("q2", "model-id", "eu-central-1")

        mock_boto3.client.assert_called_once()

    @patch("backend_orchestrator.tools.hyde.boto3")
    def test_passes_correct_model_and_config(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": "doc"}]}}}

        generate_hypothetical_document("query", "my-model-id", "eu-central-1")

        call_kwargs = mock_client.converse.call_args[1]
        assert call_kwargs["modelId"] == "my-model-id"
        assert call_kwargs["inferenceConfig"]["maxTokens"] == 300
        assert call_kwargs["inferenceConfig"]["temperature"] == 0.5
