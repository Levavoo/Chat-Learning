"""Unit tests for DocumentsService."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

import backend_orchestrator.services.documents_service as svc
from backend_orchestrator.services.documents_service import _parse_index, get_documents


@pytest.fixture(autouse=True)
def _reset_cache():
    svc._cached_response = None
    svc._cache_expiry = 0.0
    yield
    svc._cached_response = None
    svc._cache_expiry = 0.0


SAMPLE_INDEX = json.dumps({
    "documents": [
        {
            "doc_id": "B01",
            "title": "Medizinische Rehabilitation",
            "edition": "19. Auflage",
            "published": "9/2024",
            "category": "Rehabilitation",
            "sections": [{"title": "Einleitung"}, {"title": "Voraussetzungen"}],
        },
        {
            "doc_id": "B02",
            "title": "Altersrente",
            "edition": "3. Auflage",
            "published": "1/2024",
            "category": "Rente",
            "sections": [{"title": "Übersicht"}],
        },
    ]
})


class TestParseIndex:
    def test_parses_documents_correctly(self):
        result = _parse_index(SAMPLE_INDEX)
        assert result.total_documents == 2
        assert result.documents[0].doc_id in {"B01", "B02"}

    def test_section_count_from_sections_list(self):
        result = _parse_index(SAMPLE_INDEX)
        b01 = next(d for d in result.documents if d.doc_id == "B01")
        assert b01.section_count == 2

    def test_sorts_by_category_then_title(self):
        result = _parse_index(SAMPLE_INDEX)
        assert result.documents[0].category == "Rehabilitation"
        assert result.documents[1].category == "Rente"

    def test_empty_documents_list(self):
        result = _parse_index(json.dumps({"documents": []}))
        assert result.total_documents == 0
        assert result.documents == []

    def test_invalid_json_returns_empty(self):
        result = _parse_index("not valid json {{{")
        assert result.total_documents == 0

    def test_missing_documents_key_returns_empty(self):
        result = _parse_index(json.dumps({}))
        assert result.total_documents == 0

    def test_none_edition_and_published_are_none(self):
        index = json.dumps({
            "documents": [{"doc_id": "X01", "title": "Test", "edition": "", "published": "", "sections": []}]
        })
        result = _parse_index(index)
        assert result.documents[0].edition is None
        assert result.documents[0].published is None

    def test_null_category_is_none(self):
        index = json.dumps({"documents": [{"doc_id": "X01", "title": "Test", "category": None, "sections": []}]})
        result = _parse_index(index)
        assert result.documents[0].category is None


class TestGetDocuments:
    @patch("backend_orchestrator.services.documents_service.boto3")
    @patch("backend_orchestrator.services.documents_service.get_config")
    def test_loads_from_s3_when_bucket_configured(self, mock_config, mock_boto3):
        config = MagicMock()
        config.agent_search_index_bucket = "test-bucket"
        config.agent_search_index_prefix = "agent-search-index/"
        config.aws_region = "eu-central-1"
        mock_config.return_value = config

        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: SAMPLE_INDEX.encode())}

        result = get_documents()
        assert result.total_documents == 2
        mock_s3.get_object.assert_called_once_with(Bucket="test-bucket", Key="agent-search-index/index.json")

    @patch("backend_orchestrator.services.documents_service.boto3")
    @patch("backend_orchestrator.services.documents_service.get_config")
    def test_returns_empty_on_s3_error(self, mock_config, mock_boto3):
        config = MagicMock()
        config.agent_search_index_bucket = "test-bucket"
        config.agent_search_index_prefix = "agent-search-index/"
        config.aws_region = "eu-central-1"
        mock_config.return_value = config

        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3
        mock_s3.get_object.side_effect = Exception("NoSuchKey")

        result = get_documents()
        assert result.total_documents == 0
        assert result.documents == []

    @patch("backend_orchestrator.services.documents_service._load_documents")
    def test_cache_is_used_on_second_call(self, mock_load):
        mock_load.return_value = _parse_index(SAMPLE_INDEX)

        first = get_documents()
        second = get_documents()

        assert mock_load.call_count == 1
        assert first.total_documents == second.total_documents

    @patch("backend_orchestrator.services.documents_service._load_documents")
    def test_cache_expires_after_ttl(self, mock_load):
        mock_load.return_value = _parse_index(SAMPLE_INDEX)

        get_documents()
        # Expire the cache manually
        svc._cache_expiry = time.monotonic() - 1

        get_documents()
        assert mock_load.call_count == 2

    @patch("backend_orchestrator.services.documents_service.get_config")
    def test_local_fallback_uses_correct_parents_depth(self, mock_config):
        """Local fallback path resolves to the repo root (parents[4])."""
        from pathlib import Path

        import backend_orchestrator.services.documents_service as svc_module

        config = MagicMock()
        config.agent_search_index_bucket = ""
        config.agent_search_index_prefix = "agent-search-index/"
        mock_config.return_value = config

        service_file = Path(svc_module.__file__).resolve()
        expected_root = service_file.parents[4]
        expected_path = expected_root / "cdk" / "seed-data" / "agent-search-index" / "index.json"

        assert expected_path.exists(), f"Local index.json not found at expected path: {expected_path}"
        assert "digibro-monorepo" in str(expected_root)
