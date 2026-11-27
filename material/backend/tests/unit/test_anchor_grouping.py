"""Tests for anchor-retrieval logical-document grouping (#699)."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

from backend_orchestrator.tools import kb_retrieval
from backend_orchestrator.tools.kb_retrieval import (
    _apply_anchor_retrieval,
    _doc_key,
    _physical_chunk_id,
)


class TestDocKey(unittest.TestCase):
    def test_regular_brochure_chunk_uses_folder_stem(self):
        self.assertEqual(
            _doc_key("docs/318_Reha-Nachsorge/318_Reha-Nachsorge_0001.md", ""),
            "318_Reha-Nachsorge",
        )

    def test_second_chunk_of_same_brochure_shares_key(self):
        first = _doc_key("docs/318_Reha-Nachsorge/318_Reha-Nachsorge_0001.md", "")
        seventh = _doc_key("docs/318_Reha-Nachsorge/318_Reha-Nachsorge_0007.md", "")
        self.assertEqual(first, seventh)

    def test_merkblatt_chunk(self):
        self.assertEqual(_doc_key("docs/R0101/R0101_0004.md", ""), "R0101")

    def test_note_sub_document_folds_into_parent(self):
        self.assertEqual(
            _doc_key("docs/R0101_note_000/R0101_note_000_0000.md", ""),
            "R0101",
        )

    def test_table_sub_document_folds_into_parent(self):
        self.assertEqual(
            _doc_key(
                "docs/318_Reha-Nachsorge_table_002/318_Reha-Nachsorge_table_002_0000.md",
                "",
            ),
            "318_Reha-Nachsorge",
        )

    def test_main_note_and_table_of_one_brochure_share_one_key(self):
        """AC: main + note + table of one brochure resolve to one _doc_key."""
        stem = "402_Kindererziehung_DE_20-Aufl_2026-04_digibro"
        main = _doc_key(f"docs/{stem}/{stem}_0000.md", "")
        note = _doc_key(f"docs/{stem}_note_000/{stem}_note_000_0000.md", "")
        table = _doc_key(f"docs/{stem}_table_001/{stem}_table_001_0000.md", "")
        self.assertEqual(main, stem)
        self.assertEqual({main, note, table}, {stem})

    def test_faq_categories_are_one_logical_document(self):
        first = _doc_key("docs/faq-a-und-b/faq-a-und-b_0000.md", "")
        sixth = _doc_key("docs/faq-a-und-b/faq-a-und-b_0005.md", "")
        self.assertEqual(first, "faq-a-und-b")
        self.assertEqual(first, sixth)

    def test_release_prefixed_and_bm25_key_resolve_equal(self):
        """The immutable-release semantic key and the legacy BM25 key are one document."""
        semantic = _doc_key("releases/v3.22.0/processed/docs/B10_Rente/B10_Rente_0000.md", "")
        bm25 = _doc_key("docs/B10_Rente/B10_Rente_0000.md", "")
        self.assertEqual(semantic, "B10_Rente")
        self.assertEqual(semantic, bm25)

    def test_shared_prefix_folders_never_merge(self):
        self.assertNotEqual(
            _doc_key("docs/B10/B10_0000.md", ""),
            _doc_key("docs/B100/B100_0000.md", ""),
        )
        self.assertEqual(_doc_key("docs/B10/B10_0000.md", ""), "B10")
        self.assertEqual(_doc_key("docs/B100/B100_0000.md", ""), "B100")

    def test_source_uri_is_used_when_s3_key_missing(self):
        self.assertEqual(_doc_key("", "s3://bucket/docs/R0101/R0101_0004.md"), "R0101")

    def test_legacy_bare_chunk_file_uses_parent_folder(self):
        self.assertEqual(_doc_key("B01_Medizin/chunk_0000.md", ""), "B01_Medizin")

    def test_legacy_flat_chunk_suffix_still_stripped(self):
        self.assertEqual(_doc_key("docs/B01_Medizin_chunk_0003.md", ""), "B01_Medizin")

    def test_legacy_dot_chunk_suffix_still_stripped(self):
        self.assertEqual(_doc_key("docs/R0815.chunk.2", ""), "R0815")

    def test_empty_input_is_unknown_document(self):
        self.assertEqual(_doc_key("", ""), "unknown_document")


class TestPhysicalChunkId(unittest.TestCase):
    def test_semantic_and_bm25_copies_share_one_physical_id(self):
        semantic = _physical_chunk_id("releases/v3.22.0/processed/docs/B01/B01_0000.md", "")
        bm25 = _physical_chunk_id("docs/B01/B01_0000.md", "")
        self.assertEqual(semantic, "B01/B01_0000.md")
        self.assertEqual(semantic, bm25)

    def test_distinct_chunks_have_distinct_ids(self):
        self.assertNotEqual(
            _physical_chunk_id("docs/B01/B01_0000.md", ""),
            _physical_chunk_id("docs/B01/B01_0001.md", ""),
        )

    def test_uri_form_is_reduced_to_path(self):
        self.assertEqual(
            _physical_chunk_id("", "s3://bucket/docs/R0101/R0101_0004.md"),
            "R0101/R0101_0004.md",
        )


class TestCorpusGrouping(unittest.TestCase):
    def test_representative_corpus_groups_to_the_logical_model(self):
        keys = [
            "docs/318_Reha-Nachsorge/318_Reha-Nachsorge_0000.md",
            "docs/318_Reha-Nachsorge/318_Reha-Nachsorge_0001.md",
            "docs/318_Reha-Nachsorge_table_002/318_Reha-Nachsorge_table_002_0000.md",
            "docs/R0101/R0101_0000.md",
            "docs/R0101/R0101_0004.md",
            "docs/R0101_note_000/R0101_note_000_0000.md",
            "releases/v3.22.0/processed/docs/402_Kindererziehung/402_Kindererziehung_0000.md",
            "docs/402_Kindererziehung/402_Kindererziehung_0000.md",
            "docs/402_Kindererziehung/402_Kindererziehung_0009.md",
            "docs/faq-a-und-b/faq-a-und-b_0000.md",
            "docs/faq-a-und-b/faq-a-und-b_0003.md",
            "docs/faq-a-und-b/faq-a-und-b_0010.md",
        ]
        groups: dict[str, int] = {}
        for key in keys:
            groups[_doc_key(key, "")] = groups.get(_doc_key(key, ""), 0) + 1

        self.assertEqual(
            set(groups),
            {"318_Reha-Nachsorge", "R0101", "402_Kindererziehung", "faq-a-und-b"},
        )
        self.assertLess(len(groups), len(keys))
        self.assertTrue(all(count > 1 for count in groups.values()), groups)


def _anchor_config() -> MagicMock:
    config = MagicMock()
    config.anchor_s_tier_guaranteed = False
    config.anchor_max_docs = 5
    config.anchor_min_docs = 1
    config.anchor_chunks_per_doc = 3
    config.anchor_rare_term_boost = 1.0
    config.kb_retrieval_results = 10
    config.bm25_weight = 1.0
    return config


class TestApplyAnchorRetrieval(unittest.TestCase):
    def setUp(self):
        kb_retrieval._priority_map = None

    tearDown = setUp

    def test_multiple_chunks_of_one_brochure_compete_under_one_anchor(self):
        stem = "318_Reha-Nachsorge"
        semantic = [
            {
                "s3_key": f"releases/v3.22.0/processed/docs/{stem}/{stem}_0000.md",
                "content": "c0",
                "metadata": {},
                "source_uri": "",
                "score": 0,
                "rrf_score": 0.9,
            },
            {
                "s3_key": f"docs/{stem}/{stem}_0001.md",
                "content": "c1",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.8,
            },
            {
                "s3_key": f"docs/{stem}/{stem}_0002.md",
                "content": "c2",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.7,
            },
            {"s3_key": "docs/R0101/R0101_0000.md", "content": "r0", "metadata": {}, "source_uri": "", "rrf_score": 0.4},
        ]
        # The BM25 copy of the release-prefixed physical chunk above (lower score).
        bm25 = [{"chunk_id": f"docs/{stem}/{stem}_0000.md", "content": "c0", "score": 0.85, "metadata": {}}]

        with patch.object(kb_retrieval, "_load_priority_map", return_value={}):
            result = _apply_anchor_retrieval(semantic, bm25, "reha nachsorge", None, _anchor_config())

        anchor_docs = {c.get("anchor_document") for c in result}
        self.assertIn(stem, anchor_docs)
        picked_for_brochure = [c for c in result if c.get("anchor_document") == stem]
        self.assertEqual(len(picked_for_brochure), 3)

    def test_semantic_and_bm25_duplicate_of_one_chunk_not_emitted_twice(self):
        stem = "318_Reha-Nachsorge"
        semantic = [
            {
                "s3_key": f"releases/v3.22.0/processed/docs/{stem}/{stem}_0000.md",
                "content": "c0",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.9,
            },
            {
                "s3_key": f"docs/{stem}/{stem}_0001.md",
                "content": "c1",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.8,
            },
        ]
        bm25 = [{"chunk_id": f"docs/{stem}/{stem}_0000.md", "content": "c0", "score": 0.85, "metadata": {}}]

        with patch.object(kb_retrieval, "_load_priority_map", return_value={}):
            result = _apply_anchor_retrieval(semantic, bm25, "reha", None, _anchor_config())

        physical_ids = [_physical_chunk_id(c.get("s3_key", ""), c.get("source_uri", "")) for c in result]
        self.assertEqual(physical_ids.count(f"{stem}/{stem}_0000.md"), 1)

    def test_emits_grouping_observability_fields(self):
        stem = "318_Reha-Nachsorge"
        semantic = [
            {
                "s3_key": f"releases/v3.22.0/processed/docs/{stem}/{stem}_0000.md",
                "content": "c0",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.9,
            },
            {
                "s3_key": f"docs/{stem}/{stem}_0001.md",
                "content": "c1",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.8,
            },
            {
                "s3_key": f"docs/{stem}/{stem}_0002.md",
                "content": "c2",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.7,
            },
            {"s3_key": "docs/R0101/R0101_0000.md", "content": "r0", "metadata": {}, "source_uri": "", "rrf_score": 0.4},
        ]
        bm25 = [{"chunk_id": f"docs/{stem}/{stem}_0000.md", "content": "c0", "score": 0.85, "metadata": {}}]

        with (
            patch.object(kb_retrieval, "_load_priority_map", return_value={}),
            patch.object(kb_retrieval, "logger") as mock_logger,
        ):
            _apply_anchor_retrieval(semantic, bm25, "reha", None, _anchor_config())

        grouping = [c for c in mock_logger.info.call_args_list if c.args and c.args[0] == "Anchor grouping"]
        self.assertEqual(len(grouping), 1)
        extra = grouping[0].kwargs["extra"]
        self.assertEqual(extra["input_chunks"], 5)
        self.assertEqual(extra["logical_groups"], 2)
        self.assertEqual(extra["multi_chunk_groups"], 1)
        self.assertEqual(extra["singleton_groups"], 1)
        self.assertEqual(extra["selected_anchors"], 2)
        self.assertEqual(extra["chunks_per_anchor"], {stem: 3, "R0101": 1})

    def test_sets_grouping_span_attributes(self):
        stem = "318_Reha-Nachsorge"
        semantic = [
            {
                "s3_key": f"docs/{stem}/{stem}_0000.md",
                "content": "c0",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.9,
            },
            {
                "s3_key": f"docs/{stem}/{stem}_0001.md",
                "content": "c1",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.8,
            },
        ]
        mock_span = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_span
        with (
            patch.object(kb_retrieval, "_load_priority_map", return_value={}),
            patch.object(kb_retrieval, "_get_otel_tracer") as mock_tracer,
        ):
            mock_tracer.return_value.start_as_current_span.return_value = mock_cm
            _apply_anchor_retrieval(semantic, [], "reha", None, _anchor_config())

        mock_tracer.return_value.start_as_current_span.assert_called_once_with("retrieval.anchor")
        attrs = {call.args[0]: call.args[1] for call in mock_span.set_attribute.call_args_list}
        self.assertEqual(attrs["retrieval.anchor.input_chunks"], 2)
        self.assertEqual(attrs["retrieval.anchor.logical_groups"], 1)
        self.assertEqual(attrs["retrieval.anchor.multi_chunk_groups"], 1)
        self.assertEqual(attrs["retrieval.anchor.selected_anchors"], 1)


class TestAnchorScoreScaleParity(unittest.TestCase):
    """QA regression: raw BM25 magnitude must not gate anchor selection.

    Comparing raw BM25 (~7-14) to cosine similarity (~0.3-0.7) directly meant a document
    BM25 missed could not win an anchor slot however well the vector search ranked it.
    """

    def setUp(self):
        kb_retrieval._priority_map = None

    tearDown = setUp

    @staticmethod
    def _semantic() -> list[dict]:
        return [
            {
                "s3_key": "docs/200_Altersrente/200_Altersrente_0000.md",
                "content": "altersrente",
                "metadata": {},
                "source_uri": "",
                "score": 0.42,
            },
            {
                "s3_key": "docs/204_Berechnet/204_Berechnet_0000.md",
                "content": "berechnet",
                "metadata": {},
                "source_uri": "",
                "score": 0.39,
            },
        ]

    def _run(self, bm25_score: float, max_docs: int) -> list[dict]:
        config = _anchor_config()
        config.anchor_max_docs = max_docs
        bm25 = [
            {"chunk_id": "docs/204_Berechnet/204_Berechnet_0001.md", "content": "b1", "score": 9.0, "metadata": {}},
            {
                "chunk_id": "docs/202_Hinterbliebene/202_Hinterbliebene_0000.md",
                "content": "witwenrente 60 prozent",
                "score": bm25_score,
                "metadata": {},
            },
        ]
        with patch.object(kb_retrieval, "_load_priority_map", return_value={}):
            return _apply_anchor_retrieval(self._semantic(), bm25, "rente mit 60", None, config)

    def test_semantic_only_document_can_win_a_slot_over_a_large_raw_bm25_hit(self):
        anchors = {c.get("anchor_document") for c in self._run(bm25_score=7.04, max_docs=2)}

        self.assertEqual(anchors, {"204_Berechnet", "200_Altersrente"})
        self.assertNotIn("202_Hinterbliebene", anchors)

    def test_anchor_order_is_invariant_to_raw_bm25_magnitude(self):
        """Only ranks may influence selection — never the retriever's arbitrary score scale."""
        large = [c.get("anchor_document") for c in self._run(bm25_score=7.04, max_docs=3)]
        tiny = [c.get("anchor_document") for c in self._run(bm25_score=0.004, max_docs=3)]

        self.assertEqual(large, tiny)

    def test_anchor_score_is_rank_derived_and_shared_by_duplicate_copies(self):
        results = self._run(bm25_score=7.04, max_docs=3)
        by_doc = {c.get("anchor_document"): c["anchor_score"] for c in results}

        self.assertAlmostEqual(by_doc["200_Altersrente"], 1.0 / 61)
        self.assertAlmostEqual(by_doc["202_Hinterbliebene"], 1.0 / 62)


if __name__ == "__main__":
    unittest.main()
