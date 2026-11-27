"""Tests for citation source labelling (#676)."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

from backend_orchestrator.tools import bm25_search as bm25_module
from backend_orchestrator.tools import kb_retrieval
from backend_orchestrator.tools.kb_retrieval import _build_retrieval_response, _prefetch_metadata
from backend_orchestrator.utils.uri_utils import derive_label_from_filename, get_display_name

_CHUNK_KEY = (
    "docs/402_Kindererziehung_DE_20-Aufl_2026-04_digibro/402_Kindererziehung_DE_20-Aufl_2026-04_digibro_0000.md"
)
_CHUNK_METADATA = {
    "name": "Kindererziehung: Ihr Plus für die Rente",
    "brochure_number": "F01",
    "publishing_date": "4/2026",
    "brochure_url": "https://www.deutsche-rentenversicherung.de/broschuere-kindererziehung",
}


def _release_config(artifact_id: str = "sha256-" + "a" * 64) -> MagicMock:
    """Config snapshot for an immutable retrieval release."""
    config = MagicMock()
    config.bm25_index_bucket = "release-bucket"
    config.retrieval_legacy_fallback = False
    config.retrieval_release_id = artifact_id
    config.retrieval_artifact_id = artifact_id
    config.aws_region = "eu-central-1"
    return config


class TestDeriveLabelFromFilename(unittest.TestCase):
    def test_brochure_chunk_reduces_to_topic(self):
        self.assertEqual(
            derive_label_from_filename("300_Rehabilitation_DE_20-Aufl_2025-08_digibro_0009.md"),
            "Rehabilitation",
        )

    def test_merkblatt_chunk_keeps_document_id(self):
        self.assertEqual(derive_label_from_filename("R0815_0009.md"), "R0815")

    def test_sub_document_chunk_reduces_to_parent_topic(self):
        self.assertEqual(
            derive_label_from_filename("402_Kindererziehung_DE_20-Aufl_2026-04_digibro_note_000_0000.md"),
            "Kindererziehung",
        )

    def test_empty_input_yields_neutral_label(self):
        self.assertEqual(derive_label_from_filename(""), "Unbekanntes Dokument")


class TestGetDisplayName(unittest.TestCase):
    def test_metadata_name_wins(self):
        self.assertEqual(
            get_display_name({"name": "Kindererziehung: Ihr Plus für die Rente"}, f"s3://b/{_CHUNK_KEY}"),
            "Kindererziehung: Ihr Plus für die Rente",
        )

    def test_missing_metadata_never_returns_raw_filename(self):
        label = get_display_name({}, f"s3://b/{_CHUNK_KEY}")
        self.assertNotIn(".md", label)
        self.assertNotIn("_0000", label)
        self.assertEqual(label, "Kindererziehung")


class TestCachedChunkMetadata(unittest.TestCase):

    def setUp(self):
        bm25_module._bm25_index = None

    tearDown = setUp

    def test_lookup_returns_embedded_metadata(self):
        artifact = "sha256-" + "b" * 64
        bm25_module._bm25_index = {
            "metadata_by_key": {_CHUNK_KEY: _CHUNK_METADATA},
            "retrieval_artifact_id": artifact,
        }
        self.assertEqual(
            bm25_module.get_cached_chunk_metadata(_CHUNK_KEY, _release_config(artifact)),
            _CHUNK_METADATA,
        )

    def test_lookup_rejects_index_from_another_release(self):
        bm25_module._bm25_index = {
            "metadata_by_key": {_CHUNK_KEY: _CHUNK_METADATA},
            "retrieval_artifact_id": "sha256-" + "c" * 64,
        }
        self.assertEqual(bm25_module.get_cached_chunk_metadata(_CHUNK_KEY, _release_config()), {})

    def test_lookup_without_loaded_index_is_a_no_op(self):
        self.assertEqual(bm25_module.get_cached_chunk_metadata(_CHUNK_KEY, _release_config()), {})


class TestReleaseMetadataRecovery(unittest.TestCase):
    """Sidecar reads can be denied, so the index must carry the citation."""

    def setUp(self):
        kb_retrieval._s3_client = None
        bm25_module._bm25_index = None

    tearDown = setUp

    def _load_index(self, config) -> None:
        bm25_module._bm25_index = {
            "metadata_by_key": {_CHUNK_KEY: _CHUNK_METADATA},
            "retrieval_artifact_id": config.retrieval_artifact_id,
        }

    def test_citation_uses_release_metadata_when_sidecar_is_denied(self):
        config = _release_config()
        self._load_index(config)
        results = [
            {
                "s3_key": _CHUNK_KEY,
                "content": "chunk text",
                "metadata": {},
                "source_uri": f"s3://release-bucket/{_CHUNK_KEY}",
                "rrf_score": 0.5,
                "sources": {"semantic"},
            },
        ]

        with patch.object(kb_retrieval, "_fetch_s3_metadata_sidecar", return_value={}) as sidecar:
            _build_retrieval_response(results, config, out_sources := [])

        sidecar.assert_not_called()
        self.assertEqual(out_sources[0]["sourceName"], "Kindererziehung: Ihr Plus für die Rente")
        self.assertEqual(out_sources[0]["publishingDate"], "4/2026")
        self.assertEqual(out_sources[0]["brochureNumber"], "F01")

    def test_prefetch_restores_brochure_number_for_rebuilt_bm25_hit(self):
        config = _release_config()
        self._load_index(config)
        results = [
            {
                "s3_key": _CHUNK_KEY,
                "content": "chunk text",
                "metadata": {},
                "sources": {"bm25"},
            },
        ]

        with patch.object(kb_retrieval, "_fetch_s3_metadata_sidecar", return_value={}) as sidecar:
            _prefetch_metadata(results, config)

        # Immutable release: the mutable sidecar must never be consulted.
        sidecar.assert_not_called()
        self.assertEqual(results[0]["metadata"]["brochure_number"], "F01")

    def test_chunks_of_one_document_share_one_brochure_number(self):
        """The frontend dedupes on brochureNumber, so sibling chunks must agree."""
        config = _release_config()
        sibling_key = _CHUNK_KEY.replace("_0000.md", "_0004.md")
        bm25_module._bm25_index = {
            "metadata_by_key": {_CHUNK_KEY: _CHUNK_METADATA, sibling_key: _CHUNK_METADATA},
            "retrieval_artifact_id": config.retrieval_artifact_id,
        }
        results = [
            {
                "s3_key": key,
                "content": "chunk text",
                "metadata": {} if key == _CHUNK_KEY else dict(_CHUNK_METADATA),
                "source_uri": f"s3://release-bucket/{key}",
                "rrf_score": 0.5,
                "sources": {"semantic"} if key == _CHUNK_KEY else {"bm25", "semantic"},
            }
            for key in (_CHUNK_KEY, sibling_key)
        ]

        with patch.object(kb_retrieval, "_fetch_s3_metadata_sidecar", return_value={}):
            _build_retrieval_response(results, config, out_sources := [])

        self.assertEqual({s["brochureNumber"] for s in out_sources}, {"F01"})
        self.assertEqual({s["sourceName"] for s in out_sources}, {"Kindererziehung: Ihr Plus für die Rente"})


class TestAnchorRetrievalKeepsMetadata(unittest.TestCase):
    """Regression: anchor selection used to rebuild BM25 hits with empty metadata."""

    def test_bm25_metadata_survives_anchor_conversion(self):
        config = _release_config()
        config.anchor_s_tier_guaranteed = False
        config.anchor_max_docs = 5
        config.anchor_min_docs = 1
        config.anchor_chunks_per_doc = 3
        config.anchor_rare_term_boost = 1.0
        config.kb_retrieval_results = 10
        config.bm25_weight = 1.0
        bm25_results = [{"chunk_id": _CHUNK_KEY, "content": "text", "score": 1.0, "metadata": dict(_CHUNK_METADATA)}]

        with patch.object(kb_retrieval, "_load_priority_map", return_value={}):
            converted = kb_retrieval._apply_anchor_retrieval([], bm25_results, "query", None, config)

        matching = [c for c in converted if c.get("s3_key") == _CHUNK_KEY]
        self.assertEqual(len(matching), 1, "anchor selection must return the BM25 chunk")
        self.assertEqual(matching[0]["metadata"].get("brochure_number"), "F01")
        self.assertEqual(matching[0]["metadata"].get("name"), _CHUNK_METADATA["name"])


if __name__ == "__main__":
    unittest.main()
