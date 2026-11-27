
import json
from unittest.mock import patch

import pytest

from etl.util.chunking.base import Chunk
from etl.util.chunking.llm_enrichment import (
    _apply_result,
    _parse_response,
    apply_llm_enrichment,
    set_lambda_deadline,
)


@pytest.fixture
def _enable_enrichment(monkeypatch):
    monkeypatch.setenv("ENRICHMENT_ENABLED", "true")


@pytest.fixture(autouse=True)
def _reset_deadline():
    import etl.util.chunking.llm_enrichment as mod

    mod._deadline_ms = 0
    yield
    mod._deadline_ms = 0


class TestApplyLlmEnrichment:

    def test_disabled_by_default(self):
        chunks = [Chunk(content="test", metadata={})]
        result = apply_llm_enrichment(chunks)
        assert result[0].metadata == {}

    @pytest.mark.usefixtures("_enable_enrichment")
    def test_skips_chunks_with_existing_metadata(self):
        chunks = [Chunk(content="test", metadata={"section_title": "Existing", "keywords": "a, b"})]
        with patch("etl.util.chunking.llm_enrichment._get_bedrock_client") as mock:
            result = apply_llm_enrichment(chunks)
            mock.assert_not_called()
        assert result[0].metadata["section_title"] == "Existing"

    @pytest.mark.usefixtures("_enable_enrichment")
    @patch("etl.util.chunking.llm_enrichment._get_bedrock_client")
    def test_enriches_chunk_without_metadata(self, mock_client):
        llm_response = json.dumps({
            "section_title": "Befreiung Handwerker",
            "keywords": ["Versicherungspflicht", "Handwerker"],
            "colloquial_terms": ["muss ich zahlen"],
        })
        mock_client.return_value.converse.return_value = {"output": {"message": {"content": [{"text": llm_response}]}}}
        mock_client.return_value.exceptions.ThrottlingException = Exception

        chunks = [Chunk(content="Befreiung von der Versicherungspflicht", metadata={})]
        result = apply_llm_enrichment(chunks)

        assert result[0].metadata["section_title"] == "Befreiung Handwerker"
        assert result[0].metadata["keywords"] == "Versicherungspflicht, Handwerker"
        assert result[0].metadata["colloquial_terms"] == "muss ich zahlen"

    @pytest.mark.usefixtures("_enable_enrichment")
    @patch("etl.util.chunking.llm_enrichment._get_bedrock_client")
    def test_malformed_response_leaves_metadata_empty(self, mock_client):
        mock_client.return_value.converse.return_value = {
            "output": {"message": {"content": [{"text": "no json here"}]}}
        }
        mock_client.return_value.exceptions.ThrottlingException = Exception

        chunks = [Chunk(content="test content", metadata={})]
        result = apply_llm_enrichment(chunks)

        assert "section_title" not in result[0].metadata

    @pytest.mark.usefixtures("_enable_enrichment")
    @patch("etl.util.chunking.llm_enrichment._get_bedrock_client")
    def test_does_not_overwrite_existing_section_title(self, mock_client):
        llm_response = json.dumps({
            "section_title": "LLM Title",
            "keywords": ["Versicherungspflicht"],
            "colloquial_terms": ["muss ich zahlen"],
        })
        mock_client.return_value.converse.return_value = {"output": {"message": {"content": [{"text": llm_response}]}}}
        mock_client.return_value.exceptions.ThrottlingException = Exception

        chunks = [Chunk(content="test", metadata={"section_title": "From DITA"})]
        result = apply_llm_enrichment(chunks)

        assert result[0].metadata["section_title"] == "From DITA"  # preserved, not overwritten
        assert result[0].metadata["keywords"] == "Versicherungspflicht"  # added
        assert result[0].metadata["colloquial_terms"] == "muss ich zahlen"  # added

    @pytest.mark.usefixtures("_enable_enrichment")
    @patch("etl.util.chunking.llm_enrichment._get_bedrock_client")
    def test_enriches_paragraph_fallback_chunk(self, mock_client):
        """Header-less fallback chunks are enriched despite a placeholder title.

        Regression: such chunks carry a placeholder section_title (the document
        name) but no keywords. They must still be enriched with keywords +
        colloquial_terms; the placeholder title is left untouched.
        """
        llm_response = json.dumps({
            "section_title": "Befreiung Handwerker",
            "keywords": ["Versicherungspflicht", "Handwerker"],
            "colloquial_terms": ["muss ich als handwerker zahlen"],
        })
        mock_client.return_value.converse.return_value = {"output": {"message": {"content": [{"text": llm_response}]}}}
        mock_client.return_value.exceptions.ThrottlingException = Exception

        chunks = [
            Chunk(
                content="Merkblatt zur Befreiung von der Versicherungspflicht ...",
                metadata={
                    "section_title": "Merkblatt zur Befreiung von der Versicherungspflicht (Handwerker)",
                    "chunk_type": "flat_paragraph_fallback",
                    "category": "Merkblatt",
                },
            )
        ]
        result = apply_llm_enrichment(chunks)

        assert result[0].metadata["keywords"] == "Versicherungspflicht, Handwerker"
        assert result[0].metadata["colloquial_terms"] == "muss ich als handwerker zahlen"
        # Placeholder title preserved by the per-field guard.
        assert result[0].metadata["section_title"] == (
            "Merkblatt zur Befreiung von der Versicherungspflicht (Handwerker)"
        )


class TestParseResponse:

    def test_valid_json(self):
        text = '{"section_title": "Test", "keywords": ["a"], "colloquial_terms": ["b"]}'
        result = _parse_response(text)
        assert result is not None
        assert result["section_title"] == "Test"
        assert result["keywords"] == ["a"]

    def test_json_with_preamble(self):
        text = 'Here is the result:\n{"section_title": "Test", "keywords": ["a"], "colloquial_terms": ["b"]}'
        result = _parse_response(text)
        assert result is not None
        assert result["section_title"] == "Test"

    def test_no_json(self):
        assert _parse_response("no json here") is None

    def test_missing_section_title(self):
        text = '{"keywords": ["a"], "colloquial_terms": ["b"]}'
        assert _parse_response(text) is None


class TestApplyResult:

    def test_applies_all_fields(self):
        chunk = Chunk(content="x", metadata={})
        _apply_result(
            chunk,
            {
                "section_title": "Title",
                "keywords": ["a", "b"],
                "colloquial_terms": ["c"],
            },
        )
        assert chunk.metadata["section_title"] == "Title"
        assert chunk.metadata["keywords"] == "a, b"
        assert chunk.metadata["colloquial_terms"] == "c"

    def test_does_not_overwrite(self):
        chunk = Chunk(content="x", metadata={"section_title": "Existing", "keywords": "x, y"})
        _apply_result(
            chunk,
            {
                "section_title": "New",
                "keywords": ["new"],
                "colloquial_terms": ["z"],
            },
        )
        assert chunk.metadata["section_title"] == "Existing"
        assert chunk.metadata["keywords"] == "x, y"
        assert chunk.metadata["colloquial_terms"] == "z"


class TestTimeoutGuard:

    @pytest.mark.usefixtures("_enable_enrichment")
    def test_skips_enrichment_when_deadline_near(self):
        set_lambda_deadline(30_000)  # 30s remaining
        chunks = [Chunk(content="test", metadata={})]
        result = apply_llm_enrichment(chunks)
        assert "section_title" not in result[0].metadata

    @pytest.mark.usefixtures("_enable_enrichment")
    @patch("etl.util.chunking.llm_enrichment._get_bedrock_client")
    def test_proceeds_when_sufficient_time(self, mock_client):
        set_lambda_deadline(300_000)  # 5 min remaining
        llm_response = json.dumps({
            "section_title": "Test",
            "keywords": ["a"],
            "colloquial_terms": ["b"],
        })
        mock_client.return_value.converse.return_value = {"output": {"message": {"content": [{"text": llm_response}]}}}
        mock_client.return_value.exceptions.ThrottlingException = Exception

        chunks = [Chunk(content="test", metadata={})]
        result = apply_llm_enrichment(chunks)
        assert result[0].metadata["section_title"] == "Test"

    @pytest.mark.usefixtures("_enable_enrichment")
    def test_no_deadline_set_proceeds(self):
        # _deadline_ms == 0 means no deadline
        chunks = [Chunk(content="test", metadata={"section_title": "Existing"})]
        result = apply_llm_enrichment(chunks)
        # Should proceed (but skip this chunk due to existing metadata)
        assert result[0].metadata["section_title"] == "Existing"
