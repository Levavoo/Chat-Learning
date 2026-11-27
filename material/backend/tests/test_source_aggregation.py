import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from backend_orchestrator.response_parser import parse_agent_response
from backend_orchestrator.tools import kb_retrieval
from backend_orchestrator.tools.kb_retrieval import search_knowledge_base


class TestSourceAggregation(unittest.TestCase):
    def setUp(self):
        kb_retrieval._bedrock_client = None
        kb_retrieval._priority_map = None

    @patch("backend_orchestrator.tools.kb_retrieval.boto3")
    @patch("backend_orchestrator.tools.kb_retrieval.get_config")
    def test_kb_retrieval_populates_context(self, mock_get_config, mock_boto3):
        mock_config = MagicMock()
        mock_config.knowledge_base_id = "mock-kb-id"
        mock_config.aws_region = "eu-central-1"
        mock_config.kb_retrieval_results = 10
        mock_config.hyde_enabled = False
        mock_config.kb_reranker_model_arn = ""
        mock_config.kb_reranker_results = 10
        mock_config.bm25_enabled = False
        mock_config.anchor_retrieval_enabled = False
        mock_config.content_dedup_enabled = False
        mock_get_config.return_value = mock_config

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        mock_response = {
            "retrievalResults": [
                {
                    "content": {"text": "Info from chunk 1"},
                    "metadata": {
                        "x-amz-bedrock-kb-source-uri": "s3://bucket/B01_Medizin/chunk_0000.md",
                        "x-amz-bedrock-kb-source-page-index": 1,
                        "name": "Medizinische Rehabilitation",
                    },
                },
                {
                    "content": {"text": "Info from chunk 2"},
                    "metadata": {
                        "x-amz-bedrock-kb-source-uri": "s3://bucket/AnotherFolder/chunk_9999.md",
                        "x-amz-bedrock-kb-source-page-index": 5,
                    },
                },
                {
                    "content": {"text": "Info from normal file"},
                    "metadata": {
                        "x-amz-bedrock-kb-source-uri": "s3://bucket/docs/RegularFile.pdf",
                    },
                },
            ]
        }
        mock_client.retrieve.return_value = mock_response

        result = search_knowledge_base("test query", out_sources := [])

        self.assertIn("Found 3 relevant document(s)", result)
        self.assertIn("Medizinische Rehabilitation", result)
        self.assertIn("AnotherFolder", result)
        # #676: file extension must be stripped from the citizen-facing label.
        self.assertIn("RegularFile", result)
        self.assertNotIn("RegularFile.pdf", result)

        self.assertEqual(len(out_sources), 3)

        # #871: documentId is a stable per-document stem derived from the S3 key, never the raw URI.
        self.assertEqual(out_sources[0]["documentId"], "B01_Medizin")
        self.assertEqual(out_sources[0]["sourceName"], "Medizinische Rehabilitation")
        self.assertNotIn("sourceId", out_sources[0])
        self.assertNotIn("sourceLink", out_sources[0])

        self.assertEqual(out_sources[1]["documentId"], "AnotherFolder")
        self.assertEqual(out_sources[1]["sourceName"], "AnotherFolder")

        self.assertEqual(out_sources[2]["documentId"], "RegularFile")
        self.assertEqual(out_sources[2]["sourceName"], "RegularFile")

    def test_parse_agent_response_extracts_documents(self):
        agent_response_obj = {
            "result": {"content": [{"text": "Here is the answer."}]},
            "relatedDocuments": [
                {"sourceId": "doc1", "sourceName": "Document 1"},
                {"sourceId": "doc2", "sourceName": "Document 2"},
            ],
        }
        agent_response_str = json.dumps(agent_response_obj)

        text, docs = parse_agent_response(agent_response_str)

        self.assertEqual(text, "Here is the answer.")
        self.assertIsNotNone(docs)
        assert docs is not None
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0]["sourceId"], "doc1")
        self.assertEqual(docs[1]["sourceId"], "doc2")

    def test_parse_agent_response_handles_no_documents(self):
        agent_response_obj = {"result": {"content": [{"text": "Just text."}]}}
        agent_response_str = json.dumps(agent_response_obj)

        text, docs = parse_agent_response(agent_response_str)

        self.assertEqual(text, "Just text.")
        self.assertIsNone(docs)

    @patch("backend_orchestrator.tools.kb_retrieval.boto3")
    @patch("backend_orchestrator.tools.kb_retrieval.get_config")
    def test_kb_retrieval_includes_brochure_url(self, mock_get_config, mock_boto3):
        mock_config = MagicMock()
        mock_config.knowledge_base_id = "mock-kb-id"
        mock_config.aws_region = "eu-central-1"
        mock_config.kb_retrieval_results = 10
        mock_config.hyde_enabled = False
        mock_config.kb_reranker_model_arn = ""
        mock_config.kb_reranker_results = 10
        mock_config.bm25_enabled = False
        mock_config.anchor_retrieval_enabled = False
        mock_config.content_dedup_enabled = False
        mock_get_config.return_value = mock_config

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        mock_response = {
            "retrievalResults": [
                {
                    "content": {"text": "Info from brochure with URL"},
                    "metadata": {
                        "x-amz-bedrock-kb-source-uri": "s3://bucket/B01_Medizin/chunk_0000.md",
                        "name": "Medizinische Rehabilitation",
                        "brochure_url": "https://www.deutsche-rentenversicherung.de/SharedDocs/Downloads/DE/Broschueren/national/medizinische_rehabilitation.pdf",
                    },
                },
                {
                    "content": {"text": "Info from chunk without URL"},
                    "metadata": {
                        "x-amz-bedrock-kb-source-uri": "s3://bucket/AnotherFolder/chunk_9999.md",
                        "name": "Another Document",
                    },
                },
            ]
        }
        mock_client.retrieve.return_value = mock_response

        search_knowledge_base("test query", out_sources := [])

        self.assertEqual(len(out_sources), 2)

        self.assertIn("brochureUrl", out_sources[0])
        self.assertEqual(
            out_sources[0]["brochureUrl"],
            "https://www.deutsche-rentenversicherung.de/SharedDocs/Downloads/DE/Broschueren/national/medizinische_rehabilitation.pdf",
        )

        self.assertIn("brochureUrl", out_sources[1])
        self.assertIsNone(out_sources[1]["brochureUrl"])


if __name__ == "__main__":
    unittest.main()
