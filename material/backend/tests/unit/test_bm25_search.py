"""Tests for BM25 search module: index loading, search, and retry behavior."""

import json
import time
import unittest
from unittest.mock import MagicMock, patch

from backend_orchestrator.tools import bm25_search
from backend_orchestrator.tools.bm25_search import _load_index
from backend_orchestrator.tools.bm25_search import bm25_search as do_bm25_search
from bm25_shared.tokenizer import tokenize


class TestBm25Search(unittest.TestCase):
    def setUp(self):
        bm25_search._bm25_index = None
        bm25_search._bm25_load_failed_until = 0
        bm25_search._bm25_cache_artifact_id = None
        bm25_search._bm25_failed_artifact_id = None

    @patch("backend_orchestrator.tools.bm25_search.boto3")
    @patch("backend_orchestrator.tools.bm25_search.get_config")
    def test_load_index_success(self, mock_get_config, mock_boto3):
        mock_config = MagicMock()
        mock_config.bm25_index_bucket = "test-bucket"
        mock_config.bm25_index_key = "bm25_index/index.json"
        mock_config.aws_region = "eu-central-1"
        mock_get_config.return_value = mock_config

        index_data = {
            "corpus": [["rente", "test"]],
            "chunk_ids": ["docs/a.md"],
            "chunk_contents": ["content a"],
        }

        def fake_download(bucket, key, path):
            with open(path, "w") as f:
                json.dump(index_data, f)

        mock_client = MagicMock()
        mock_client.download_file.side_effect = fake_download
        mock_boto3.client.return_value = mock_client

        result = _load_index()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["chunk_ids"], ["docs/a.md"])

    @patch("backend_orchestrator.tools.bm25_search.get_config")
    def test_load_index_no_bucket_configured(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.bm25_index_bucket = ""
        mock_get_config.return_value = mock_config

        result = _load_index()
        self.assertIsNone(result)

    @patch("backend_orchestrator.tools.bm25_search.boto3")
    @patch("backend_orchestrator.tools.bm25_search.get_config")
    def test_load_index_s3_error_retries_after_interval(self, mock_get_config, mock_boto3):
        mock_config = MagicMock()
        mock_config.bm25_index_bucket = "test-bucket"
        mock_config.bm25_index_key = "bm25_index/index.json"
        mock_config.aws_region = "eu-central-1"
        mock_get_config.return_value = mock_config

        mock_client = MagicMock()
        mock_client.download_file.side_effect = Exception("S3 timeout")
        mock_boto3.client.return_value = mock_client

        result = _load_index()
        self.assertIsNone(result)

        result = _load_index()
        self.assertIsNone(result)
        self.assertEqual(mock_client.download_file.call_count, 1)

        bm25_search._bm25_load_failed_until = time.time() - 1
        _load_index()
        self.assertEqual(mock_client.download_file.call_count, 2)

    @patch("backend_orchestrator.tools.bm25_search.boto3")
    @patch("backend_orchestrator.tools.bm25_search.get_config")
    def test_search_returns_top_k_results(self, mock_get_config, mock_boto3):
        mock_config = MagicMock()
        mock_config.bm25_index_bucket = "test-bucket"
        mock_config.bm25_index_key = "bm25_index/index.json"
        mock_config.aws_region = "eu-central-1"
        mock_get_config.return_value = mock_config

        # Build the corpus the same way the ETL does — tokenize the chunk contents, since
        # hardcoded raw tokens would skip stemming and wouldn't match a stemmed query.
        chunk_contents = ["Rente Berechnung", "Medizin Reha", "Rente Alter Versicherung"]
        index_data = {
            "corpus": [tokenize(c) for c in chunk_contents],
            "chunk_ids": ["docs/a.md", "docs/b.md", "docs/c.md"],
            "chunk_contents": chunk_contents,
        }

        def fake_download(bucket, key, path):
            with open(path, "w") as f:
                json.dump(index_data, f)

        mock_client = MagicMock()
        mock_client.download_file.side_effect = fake_download
        mock_boto3.client.return_value = mock_client

        results = do_bm25_search("rente berechnung", top_k=2)
        self.assertLessEqual(len(results), 2)
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("chunk_id", r)
            self.assertIn("score", r)
            self.assertIn("content", r)
            self.assertGreater(r["score"], 0)

    def test_search_returns_empty_when_index_not_loaded(self):
        bm25_search._bm25_load_failed_until = time.time() + 60
        results = do_bm25_search("test query")
        self.assertEqual(results, [])

    @patch("backend_orchestrator.tools.bm25_search._load_index")
    def test_search_returns_empty_for_stopword_only_query(self, mock_load):
        mock_load.return_value = {"bm25": MagicMock(), "chunk_ids": [], "chunk_contents": []}
        results = do_bm25_search("der die das")
        self.assertEqual(results, [])

    @patch("backend_orchestrator.tools.bm25_search.boto3")
    def test_release_change_invalidates_cache_immediately_and_uses_embedded_metadata(self, mock_boto3):
        """A selector change reloads immediately, without waiting for the legacy five-minute TTL."""
        release_a = f"sha256-{'a' * 64}"
        release_b = f"sha256-{'b' * 64}"
        payloads = {
            release_a: {
                "release_id": release_a,
                "bm25_tokenizer_revision": "cistem-decompound-v1",
                "corpus": [["ren"], ["medizin"], ["therapi"]],
                "chunk_ids": ["docs/a.md", "docs/a2.md", "docs/a3.md"],
                "chunk_contents": ["Rente A", "Medizin", "Therapie"],
                "chunk_metadata": [{"brochure_number": "A"}, {}, {}],
            },
            release_b: {
                "release_id": release_b,
                "bm25_tokenizer_revision": "cistem-decompound-v1",
                "corpus": [["ren"], ["medizin"], ["therapi"]],
                "chunk_ids": ["docs/b.md", "docs/b2.md", "docs/b3.md"],
                "chunk_contents": ["Rente B", "Medizin", "Therapie"],
                "chunk_metadata": [{"brochure_number": "B"}, {}, {}],
            },
        }

        def fake_download(bucket, key, path):
            release_id = release_a if release_a in key else release_b
            with open(path, "w") as f:
                json.dump(payloads[release_id], f)

        mock_client = MagicMock()
        mock_client.download_file.side_effect = fake_download
        mock_boto3.client.return_value = mock_client

        def snapshot(release_id):
            return MagicMock(
                retrieval_release_id=release_id,
                retrieval_legacy_fallback=False,
                bm25_index_bucket="release-bucket",
                bm25_index_key=f"bm25_index/releases/{release_id}/index.json",
                bm25_tokenizer_revision="cistem-decompound-v1",
                aws_region="eu-central-1",
            )

        first = do_bm25_search("Rente", retrieval_snapshot=snapshot(release_a))
        second = do_bm25_search("Rente", retrieval_snapshot=snapshot(release_b))

        self.assertEqual(first[0]["metadata"], {"brochure_number": "A"})
        self.assertEqual(second[0]["metadata"], {"brochure_number": "B"})
        self.assertEqual(second[0]["release_id"], release_b)
        self.assertEqual(mock_client.download_file.call_count, 2)

    @patch("backend_orchestrator.tools.bm25_search.boto3")
    def test_chatbot_only_release_reuses_artifact_cache_but_reports_new_release(self, mock_boto3):
        release_a = f"sha256-{'a' * 64}"
        release_b = f"sha256-{'b' * 64}"
        artifact_id = f"sha256-{'c' * 64}"
        payload = {
            "schema_version": 2,
            "release_id": release_a,
            "retrieval_artifact_id": artifact_id,
            "bm25_tokenizer_revision": "cistem-decompound-v1",
            "corpus": [["ren"], ["medizin"], ["therapi"]],
            "chunk_ids": ["docs/a.md", "docs/b.md", "docs/c.md"],
            "chunk_contents": ["Rente", "Medizin", "Therapie"],
            "chunk_metadata": [{}, {}, {}],
        }

        def fake_download(bucket, key, path):
            with open(path, "w") as f:
                json.dump(payload, f)

        mock_client = MagicMock()
        mock_client.download_file.side_effect = fake_download
        mock_boto3.client.return_value = mock_client

        def snapshot(release_id):
            return MagicMock(
                retrieval_release_id=release_id,
                retrieval_artifact_id=artifact_id,
                retrieval_legacy_fallback=False,
                bm25_index_bucket="release-bucket",
                bm25_index_key=f"bm25_index/releases/{artifact_id}/index.json",
                bm25_tokenizer_revision="cistem-decompound-v1",
                aws_region="eu-central-1",
            )

        first = do_bm25_search("Rente", retrieval_snapshot=snapshot(release_a))
        second = do_bm25_search("Rente", retrieval_snapshot=snapshot(release_b))

        self.assertEqual(first[0]["release_id"], release_a)
        self.assertEqual(second[0]["release_id"], release_b)
        self.assertEqual(mock_client.download_file.call_count, 1)


if __name__ == "__main__":
    unittest.main()
