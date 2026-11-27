"""Tests for retrieving with the raw user question alongside the agent's rephrased query.

The rephrase is not stable (e.g. 8/10 runs collapse "Kann ich mit 60 in Rente gehen?" to
"Rente mit 60 Voraussetzungen", burying B03 at semantic rank 43 while the raw question retrieves
it at rank 1). Pins three properties: the raw question is issued as a second query, the rephrase
stays primary, and a question that cannot stand without chat history is never used as a query.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

from backend_orchestrator.tools.kb_retrieval import (
    _ORIGINAL_QUERY_WEIGHT,
    _fuse_query_variants,
    _perform_search_and_enhancement,
    _standalone_query,
)

REPHRASE = "Rente mit 60 Voraussetzungen"
ORIGINAL = "Kann ich mit 60 in Rente gehen?"


def _semantic(key: str, score: float = 0.5) -> dict:
    return {
        "s3_key": key,
        "content": f"content of {key}",
        "metadata": {"brochure_number": key.split("/")[0]},
        "source_uri": f"s3://bucket/{key}",
        "score": score,
        "release_id": "legacy-environment",
    }


def _config(**overrides):
    """Retrieval enhancements off, so tests isolate the query fusion."""
    config = MagicMock()
    config.knowledge_base_id = "KB123"
    config.aws_region = "eu-central-1"
    config.kb_retrieval_results = 50
    config.bm25_enabled = False
    config.bm25_weight = 1.0
    config.metadata_routing_enabled = False
    config.anchor_retrieval_enabled = False
    config.retrieval_release_id = "legacy-environment"
    config.retrieval_legacy_fallback = True
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


class TestStandaloneQuery(unittest.TestCase):
    def test_real_question_is_used(self):
        self.assertEqual(_standalone_query(ORIGINAL, REPHRASE), ORIGINAL)

    def test_pure_back_reference_follow_up_is_rejected(self):
        """A bare "und dabei?" only means something with chat history, which retrieval lacks."""
        self.assertEqual(_standalone_query("und dabei?", "Rente mit 60 Lehrer Beamte"), "")

    def test_demonstrative_only_follow_up_is_rejected(self):
        self.assertEqual(_standalone_query("Und das?", "Grundsicherung Einkommen"), "")

    def test_follow_up_naming_a_topic_is_used(self):
        self.assertEqual(
            _standalone_query("und wenn ich Lehrer bin?", "Rente mit 60 Lehrer Beamte"),
            "und wenn ich Lehrer bin?",
        )

    def test_empty_question_is_rejected(self):
        self.assertEqual(_standalone_query("", REPHRASE), "")
        self.assertEqual(_standalone_query("   ", REPHRASE), "")

    def test_question_equal_to_rephrase_is_rejected(self):
        self.assertEqual(_standalone_query("Rente mit 60 Voraussetzungen", REPHRASE), "")
        self.assertEqual(_standalone_query("voraussetzungen rente mit 60", REPHRASE), "")

    def test_bare_number_is_not_content(self):
        self.assertEqual(_standalone_query("mit 60?", "Rente mit 60"), "")


class TestFuseQueryVariants(unittest.TestCase):
    def test_result_shape_is_preserved(self):
        """Downstream stages read results by position — fusion must not reshape them."""
        primary = [_semantic("B11/a", score=0.42)]
        fused = _fuse_query_variants(primary, [], "s3_key", _ORIGINAL_QUERY_WEIGHT)
        self.assertEqual(fused[0], primary[0])
        self.assertEqual(fused[0]["score"], 0.42)
        self.assertNotIn("rrf_score", fused[0])

    def test_secondary_only_document_survives(self):
        primary = [_semantic(f"B{i:02d}/a") for i in range(10, 20)]
        secondary = [_semantic("B03/a")]
        fused = _fuse_query_variants(primary, secondary, "s3_key", _ORIGINAL_QUERY_WEIGHT)
        self.assertIn("B03/a", [r["s3_key"] for r in fused])

    def test_agreement_outranks_either_list_alone(self):
        primary = [_semantic("B03/a"), _semantic("B11/a")]
        secondary = [_semantic("B11/a"), _semantic("B03/a")]
        fused = _fuse_query_variants(primary, secondary, "s3_key", _ORIGINAL_QUERY_WEIGHT)
        self.assertEqual(fused[0]["s3_key"], "B03/a")

    def test_primary_outranks_secondary_at_equal_rank(self):
        """Rephrase is the only text guaranteed self-contained, so it stays primary."""
        primary = [_semantic("B11/a")]
        secondary = [_semantic("B03/a")]
        fused = _fuse_query_variants(primary, secondary, "s3_key", _ORIGINAL_QUERY_WEIGHT)
        self.assertEqual([r["s3_key"] for r in fused], ["B11/a", "B03/a"])

    def test_deep_primary_hit_is_rescued_by_a_top_secondary_hit(self):
        primary = [_semantic(f"B{i:02d}/a") for i in range(10, 60)]
        primary.insert(42, _semantic("B03/a"))
        secondary = [_semantic("B03/a"), *(_semantic(f"B{i:02d}/b") for i in range(10, 30))]
        fused = _fuse_query_variants(primary, secondary, "s3_key", _ORIGINAL_QUERY_WEIGHT)
        rank = [r["s3_key"] for r in fused].index("B03/a") + 1
        self.assertLess(rank, 10, f"B03 should be rescued into the top 10, got rank {rank}")

    def test_bm25_results_fuse_on_chunk_id(self):
        primary = [{"chunk_id": "c1", "content": "x", "score": 9.0}]
        secondary = [{"chunk_id": "c2", "content": "y", "score": 7.0}]
        fused = _fuse_query_variants(primary, secondary, "chunk_id", _ORIGINAL_QUERY_WEIGHT)
        self.assertEqual([r["chunk_id"] for r in fused], ["c1", "c2"])
        self.assertEqual(fused[0]["score"], 9.0)


class TestPerformSearchIssuesBothQueries(unittest.TestCase):
    @patch("backend_orchestrator.tools.kb_retrieval._prefetch_metadata")
    @patch("backend_orchestrator.tools.kb_retrieval._semantic_search")
    def test_both_queries_are_issued(self, mock_search, _mock_prefetch):
        mock_search.side_effect = [[_semantic("B11/a")], [_semantic("B03/a")]]
        _perform_search_and_enhancement(REPHRASE, REPHRASE, _config(), "rente", ORIGINAL)
        issued = [call.args[0] for call in mock_search.call_args_list]
        self.assertEqual(issued, [REPHRASE, ORIGINAL])

    @patch("backend_orchestrator.tools.kb_retrieval._prefetch_metadata")
    @patch("backend_orchestrator.tools.kb_retrieval._semantic_search")
    def test_secondary_only_document_reaches_the_pool(self, mock_search, _mock_prefetch):
        mock_search.side_effect = [[_semantic("B11/a")], [_semantic("B03/a")]]
        results = _perform_search_and_enhancement(REPHRASE, REPHRASE, _config(), "rente", ORIGINAL)
        self.assertIn("B03/a", [r["s3_key"] for r in results])

    @patch("backend_orchestrator.tools.kb_retrieval._prefetch_metadata")
    @patch("backend_orchestrator.tools.kb_retrieval._semantic_search")
    def test_hyde_query_stays_primary(self, mock_search, _mock_prefetch):
        """With HyDE on, the primary retrieve uses the hypothetical document, not the rephrase."""
        mock_search.side_effect = [[_semantic("B11/a")], [_semantic("B03/a")]]
        _perform_search_and_enhancement(REPHRASE, "hypothetical answer text", _config(), "rente", ORIGINAL)
        issued = [call.args[0] for call in mock_search.call_args_list]
        self.assertEqual(issued, ["hypothetical answer text", ORIGINAL])

    @patch("backend_orchestrator.tools.kb_retrieval._prefetch_metadata")
    @patch("backend_orchestrator.tools.kb_retrieval._semantic_search")
    def test_back_reference_follow_up_issues_one_query(self, mock_search, _mock_prefetch):
        mock_search.side_effect = [[_semantic("B11/a")]]
        _perform_search_and_enhancement("Rente mit 60 Lehrer", "Rente mit 60 Lehrer", _config(), "rente", "und dabei?")
        self.assertEqual(mock_search.call_count, 1)

    @patch("backend_orchestrator.tools.kb_retrieval._prefetch_metadata")
    @patch("backend_orchestrator.tools.kb_retrieval._semantic_search")
    def test_missing_original_question_issues_one_query(self, mock_search, _mock_prefetch):
        mock_search.side_effect = [[_semantic("B11/a")]]
        _perform_search_and_enhancement(REPHRASE, REPHRASE, _config(), "rente", "")
        self.assertEqual(mock_search.call_count, 1)

    @patch("backend_orchestrator.tools.kb_retrieval._prefetch_metadata")
    @patch("backend_orchestrator.tools.kb_retrieval._validate_bm25_release")
    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    @patch("backend_orchestrator.tools.kb_retrieval._semantic_search")
    def test_bm25_also_runs_both_queries(self, mock_search, mock_bm25, _mock_validate, _mock_prefetch):
        mock_search.side_effect = [[_semantic("B11/a")], [_semantic("B03/a")]]
        mock_bm25.side_effect = [
            [{"chunk_id": "B11/a", "content": "x", "score": 9.0, "release_id": "legacy-environment"}],
            [{"chunk_id": "B03/a", "content": "y", "score": 7.0, "release_id": "legacy-environment"}],
        ]
        results = _perform_search_and_enhancement(REPHRASE, REPHRASE, _config(bm25_enabled=True), "rente", ORIGINAL)
        issued = [call.args[0] for call in mock_bm25.call_args_list]
        self.assertEqual(issued, [REPHRASE, ORIGINAL])
        self.assertIn("B03/a", [r["s3_key"] for r in results])

    @patch("backend_orchestrator.tools.kb_retrieval._prefetch_metadata")
    @patch("backend_orchestrator.tools.kb_retrieval._validate_bm25_release")
    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    @patch("backend_orchestrator.tools.kb_retrieval._semantic_search")
    def test_bm25_release_validation_covers_the_second_query(
        self, mock_search, mock_bm25, mock_validate, _mock_prefetch
    ):
        mock_search.side_effect = [[_semantic("B11/a")], [_semantic("B03/a")]]
        mock_bm25.side_effect = [
            [{"chunk_id": "B11/a", "content": "x", "score": 9.0, "release_id": "legacy-environment"}],
            [{"chunk_id": "B03/a", "content": "y", "score": 7.0, "release_id": "other-release"}],
        ]
        _perform_search_and_enhancement(REPHRASE, REPHRASE, _config(bm25_enabled=True), "rente", ORIGINAL)
        validated = mock_validate.call_args.args[0]
        self.assertIn("other-release", [r.get("release_id") for r in validated])

    @patch("backend_orchestrator.tools.kb_retrieval._prefetch_metadata")
    @patch("backend_orchestrator.tools.kb_retrieval._semantic_search")
    def test_fused_pool_respects_the_retrieval_budget(self, mock_search, _mock_prefetch):
        mock_search.side_effect = [
            [_semantic(f"B{i:02d}/a") for i in range(50)],
            [_semantic(f"C{i:02d}/a") for i in range(50)],
        ]
        results = _perform_search_and_enhancement(REPHRASE, REPHRASE, _config(), "rente", ORIGINAL)
        self.assertEqual(len(results), 50)


if __name__ == "__main__":
    unittest.main()
