
from unittest.mock import MagicMock, patch

from etl.util.chunking.llm_context import (
    _truncate_document,
    generate_document_summary,
)


class TestTruncateDocument:

    def test_short_document_unchanged(self):
        doc = "Short document."
        assert _truncate_document(doc, max_chars=100) == doc

    def test_exact_length_unchanged(self):
        doc = "a" * 100
        assert _truncate_document(doc, max_chars=100) == doc

    def test_truncates_at_line_boundary(self):
        doc = "line1\nline2\nline3\nline4"
        result = _truncate_document(doc, max_chars=15)
        assert result == "line1\nline2"

    def test_truncates_without_newline(self):
        doc = "a" * 200
        result = _truncate_document(doc, max_chars=100)
        assert len(result) == 100


class TestGenerateDocumentSummary:

    def test_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            result = generate_document_summary("full doc")
        assert result is None

    def test_disabled_explicitly(self):
        with patch.dict("os.environ", {"CONTEXTUAL_GROUNDING_ENABLED": "false"}):
            result = generate_document_summary("full doc")
        assert result is None

    @patch("etl.util.chunking.llm_context._get_bedrock_client")
    def test_returns_llm_response(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Dieser Abschnitt behandelt Renten."}]}}
        }
        mock_get_client.return_value = mock_client

        with patch.dict("os.environ", {"CONTEXTUAL_GROUNDING_ENABLED": "true"}):
            result = generate_document_summary("full document text")

        assert result == "Dieser Abschnitt behandelt Renten."
        mock_client.converse.assert_called_once()

    @patch("etl.util.chunking.llm_context._get_bedrock_client")
    def test_returns_none_on_api_error(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.converse.side_effect = Exception("API error")
        mock_get_client.return_value = mock_client

        with patch.dict("os.environ", {"CONTEXTUAL_GROUNDING_ENABLED": "true"}):
            result = generate_document_summary("full doc")

        assert result is None

    @patch("etl.util.chunking.llm_context._get_bedrock_client")
    def test_returns_none_on_empty_response(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": "   "}]}}}
        mock_get_client.return_value = mock_client

        with patch.dict("os.environ", {"CONTEXTUAL_GROUNDING_ENABLED": "true"}):
            result = generate_document_summary("full doc")

        assert result is None

    @patch("etl.util.chunking.llm_context._get_bedrock_client")
    def test_uses_configured_model_id(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": "context"}]}}}
        mock_get_client.return_value = mock_client

        with patch.dict(
            "os.environ",
            {
                "CONTEXTUAL_GROUNDING_ENABLED": "true",
                "CONTEXTUAL_GROUNDING_MODEL_ID": "custom-model",
            },
        ):
            generate_document_summary("doc")

        call_kwargs = mock_client.converse.call_args[1]
        assert call_kwargs["modelId"] == "custom-model"

    @patch("etl.util.chunking.llm_context.time.sleep")
    @patch("etl.util.chunking.llm_context._get_bedrock_client")
    def test_applies_delay(self, mock_get_client, mock_sleep):
        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": "ctx"}]}}}
        mock_get_client.return_value = mock_client

        with patch.dict(
            "os.environ",
            {
                "CONTEXTUAL_GROUNDING_ENABLED": "true",
                "CONTEXTUAL_GROUNDING_DELAY_MS": "500",
            },
        ):
            generate_document_summary("doc")

        mock_sleep.assert_called_once_with(0.5)

    @patch("etl.util.chunking.llm_context._get_bedrock_client")
    def test_no_delay_by_default(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": "ctx"}]}}}
        mock_get_client.return_value = mock_client

        with (
            patch.dict("os.environ", {"CONTEXTUAL_GROUNDING_ENABLED": "true"}),
            patch("etl.util.chunking.llm_context.time.sleep") as mock_sleep,
        ):
            generate_document_summary("doc")

        mock_sleep.assert_not_called()

    @patch("etl.util.chunking.llm_context._get_bedrock_client")
    def test_inference_config(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": "ctx"}]}}}
        mock_get_client.return_value = mock_client

        with patch.dict("os.environ", {"CONTEXTUAL_GROUNDING_ENABLED": "true"}):
            generate_document_summary("doc")

        call_kwargs = mock_client.converse.call_args[1]
        assert call_kwargs["inferenceConfig"] == {"temperature": 0.0, "maxTokens": 256}
