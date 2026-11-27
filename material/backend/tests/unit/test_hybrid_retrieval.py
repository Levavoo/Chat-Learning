import unittest
from typing import ClassVar
from unittest.mock import MagicMock, patch

from backend_orchestrator.tools import kb_retrieval
from backend_orchestrator.tools.kb_retrieval import (
    _CROSS_DOMAIN_PENALTY,
    _OUT_OF_SCOPE_MESSAGE,
    _YEAR_MATCH_BOOST,
    _apply_year_match_boost,
    _build_retrieval_response,
    _extract_brochure_number,
    _extract_query_years,
    _filter_by_domain,
    _has_lexical_hit,
    _is_rare_term_query,
    _keyword_phrase_matches,
    _merge_scoped_results,
    _route_target_brochure,
    _rrf_fusion,
    search_knowledge_base,
)


class TestRrfFusion(unittest.TestCase):
    def test_semantic_only(self):
        semantic = [
            {"s3_key": "docs/a.md", "content": "a", "metadata": {"name": "A"}, "source_uri": "s3://b/docs/a.md"},
            {"s3_key": "docs/b.md", "content": "b", "metadata": {"name": "B"}, "source_uri": "s3://b/docs/b.md"},
        ]
        result = _rrf_fusion(semantic, [], bm25_weight=1.0)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["s3_key"], "docs/a.md")
        self.assertGreater(result[0]["rrf_score"], result[1]["rrf_score"])

    def test_bm25_only(self):
        bm25 = [
            {"chunk_id": "docs/x.md", "content": "x", "score": 5.0},
            {"chunk_id": "docs/y.md", "content": "y", "score": 3.0},
        ]
        result = _rrf_fusion([], bm25, bm25_weight=1.0)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["s3_key"], "docs/x.md")
        self.assertEqual(result[0]["sources"], {"bm25"})

    def test_overlapping_results_merged(self):
        semantic = [
            {"s3_key": "docs/shared.md", "content": "shared", "metadata": {}, "source_uri": "s3://b/docs/shared.md"},
        ]
        bm25 = [
            {"chunk_id": "docs/shared.md", "content": "shared", "score": 5.0},
        ]
        result = _rrf_fusion(semantic, bm25, bm25_weight=1.0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sources"], {"semantic", "bm25"})
        semantic_only = _rrf_fusion(semantic, [], bm25_weight=1.0)
        self.assertGreater(result[0]["rrf_score"], semantic_only[0]["rrf_score"])

    def test_overlapping_results_keep_embedded_bm25_metadata(self):
        """A hybrid hit must carry the release index metadata, since the immutable path has no sidecar."""
        semantic = [
            {"s3_key": "docs/shared.md", "content": "shared", "metadata": {}, "source_uri": "s3://b/docs/shared.md"},
        ]
        bm25 = [
            {"chunk_id": "docs/shared.md", "content": "shared", "score": 5.0, "metadata": {"brochure_number": "123"}},
        ]
        result = _rrf_fusion(semantic, bm25, bm25_weight=1.0)
        self.assertEqual(result[0]["metadata"], {"brochure_number": "123"})

    def test_overlapping_results_prefer_semantic_metadata(self):
        """Semantic metadata stays authoritative; the release index only fills gaps."""
        semantic = [
            {
                "s3_key": "docs/shared.md",
                "content": "shared",
                "metadata": {"brochure_number": "semantic"},
                "source_uri": "s3://b/docs/shared.md",
            },
        ]
        bm25 = [
            {
                "chunk_id": "docs/shared.md",
                "content": "shared",
                "score": 5.0,
                "metadata": {"brochure_number": "bm25", "category": "Rente"},
            },
        ]
        result = _rrf_fusion(semantic, bm25, bm25_weight=1.0)
        self.assertEqual(result[0]["metadata"], {"brochure_number": "semantic", "category": "Rente"})

    def test_bm25_weight_affects_ordering(self):
        semantic = [
            {"s3_key": "docs/sem.md", "content": "sem", "metadata": {}, "source_uri": "s3://b/docs/sem.md"},
        ]
        bm25 = [
            {"chunk_id": "docs/bm25.md", "content": "bm25", "score": 5.0},
        ]
        result_high = _rrf_fusion(semantic, bm25, bm25_weight=10.0)
        self.assertEqual(result_high[0]["s3_key"], "docs/bm25.md")

        result_low = _rrf_fusion(semantic, bm25, bm25_weight=0.01)
        self.assertEqual(result_low[0]["s3_key"], "docs/sem.md")

    def test_empty_s3_key_gets_fallback(self):
        """Semantic results with empty s3_key must get a synthetic fallback key."""
        semantic = [
            {"s3_key": "", "content": "no key", "metadata": {}, "source_uri": "s3://b/unknown"},
        ]
        result = _rrf_fusion(semantic, [], bm25_weight=1.0)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["s3_key"].startswith("semantic_unkeyed:"))


class TestSearchKnowledgeBase(unittest.TestCase):
    def setUp(self):
        kb_retrieval._bedrock_client = None
        kb_retrieval._s3_client = None
        kb_retrieval._priority_map = None

    @patch("backend_orchestrator.tools.kb_retrieval._perform_search_and_enhancement")
    @patch("backend_orchestrator.tools.kb_retrieval.get_config")
    def test_hybrid_search_populates_context(self, mock_get_config, mock_perform_search):
        mock_config = MagicMock()
        mock_config.knowledge_base_id = "kb-123"
        mock_config.aws_region = "eu-central-1"
        mock_config.kb_retrieval_results = 10
        mock_config.bm25_enabled = True
        mock_config.bm25_weight = 1.0
        mock_config.bm25_index_bucket = "test-bucket"
        mock_config.hyde_enabled = False
        mock_config.kb_reranker_model_arn = ""
        mock_config.kb_reranker_results = 10
        mock_config.content_dedup_enabled = False
        mock_get_config.return_value = mock_config

        mock_perform_search.return_value = [
            {
                "s3_key": "docs/sem.md",
                "content": "Semantic result content",
                "metadata": {"name": "Semantic Doc"},
                "source_uri": "s3://test-bucket/docs/sem.md",
                "rrf_score": 0.8,
                "sources": {"semantic", "bm25"},
            },
            {
                "s3_key": "docs/bm25only.md",
                "content": "BM25 only content",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.4,
                "sources": {"bm25"},
            },
        ]

        result = search_knowledge_base("rente berechnung", out_sources := [])

        self.assertIn("Found 2 relevant document(s)", result)
        self.assertEqual(len(out_sources), 2)

        self.assertEqual(out_sources[0]["documentId"], "sem")

    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    @patch("backend_orchestrator.tools.kb_retrieval.boto3")
    @patch("backend_orchestrator.tools.kb_retrieval.get_config")
    def test_fallback_to_semantic_when_bm25_fails(self, mock_get_config, mock_boto3, mock_bm25):
        """Must gracefully degrade to semantic-only when BM25 search raises."""
        mock_config = MagicMock()
        mock_config.knowledge_base_id = "kb-123"
        mock_config.aws_region = "eu-central-1"
        mock_config.kb_retrieval_results = 10
        mock_config.bm25_enabled = True
        mock_config.bm25_weight = 1.0
        mock_config.bm25_index_bucket = "test-bucket"
        mock_config.hyde_enabled = False
        mock_config.kb_reranker_model_arn = ""
        mock_config.kb_reranker_results = 10
        mock_config.anchor_retrieval_enabled = False
        mock_get_config.return_value = mock_config

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {"text": "Semantic content"},
                    "metadata": {
                        "x-amz-bedrock-kb-source-uri": "s3://test-bucket/docs/a.md",
                        "name": "Doc A",
                    },
                },
            ]
        }

        mock_bm25.side_effect = Exception("Index not available")

        result = search_knowledge_base("test query", out_sources := [])

        self.assertIn("Found 1 relevant document(s)", result)
        self.assertEqual(len(out_sources), 1)

    @patch("backend_orchestrator.tools.kb_retrieval.snapshot_retrieval_config")
    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    @patch("backend_orchestrator.tools.kb_retrieval.boto3")
    @patch("backend_orchestrator.tools.kb_retrieval.get_config")
    def test_bm25_failure_logs_retrieval_release_id(self, mock_get_config, mock_boto3, mock_bm25, mock_snapshot):
        """The swallowed BM25-failure exception must log retrieval_release_id. A CloudWatch Logs
        MetricFilter watches this line for the vector/BM25 release_id mismatch alarm (any BM25
        failure, including _validate_bm25_release's mismatch ValueError, lands here)."""
        mock_config = MagicMock()
        mock_config.knowledge_base_id = "kb-123"
        mock_config.aws_region = "eu-central-1"
        mock_config.kb_retrieval_results = 10
        mock_config.bm25_enabled = True
        mock_config.bm25_weight = 1.0
        mock_config.bm25_index_bucket = "test-bucket"
        mock_config.hyde_enabled = False
        mock_config.kb_reranker_model_arn = ""
        mock_config.kb_reranker_results = 10
        mock_config.anchor_retrieval_enabled = False
        mock_config.retrieval_release_id = "sha256-expectedrelease"
        mock_get_config.return_value = mock_config
        # search_knowledge_base snapshots via snapshot_retrieval_config(get_config()), not
        # get_config() directly; pass the same config through unchanged so retrieval_release_id
        # is preserved.
        mock_snapshot.return_value = mock_config

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {"text": "Semantic content"},
                    "metadata": {
                        "x-amz-bedrock-kb-source-uri": "s3://test-bucket/docs/a.md",
                        "name": "Doc A",
                    },
                },
            ]
        }

        mock_bm25.side_effect = ValueError(
            "BM25 results do not match request release 'sha256-expectedrelease': ['sha256-other']"
        )

        with self.assertLogs(level="ERROR") as captured:
            search_knowledge_base("test query", out_sources := [])

        self.assertEqual(len(out_sources), 1)
        matching = [r for r in captured.records if "BM25 search failed" in r.getMessage()]
        self.assertEqual(len(matching), 1)
        # retrieval_release_id is attached dynamically via logger's `extra=`, not a static
        # LogRecord attribute.
        self.assertEqual(
            matching[0].retrieval_release_id,  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            "sha256-expectedrelease",
        )

    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    @patch("backend_orchestrator.tools.kb_retrieval.boto3")
    @patch("backend_orchestrator.tools.kb_retrieval.get_config")
    def test_semantic_only_when_bm25_disabled(self, mock_get_config, mock_boto3, mock_bm25):
        mock_config = MagicMock()
        mock_config.knowledge_base_id = "kb-123"
        mock_config.aws_region = "eu-central-1"
        mock_config.kb_retrieval_results = 10
        mock_config.bm25_enabled = False
        mock_config.bm25_weight = 1.0
        mock_config.bm25_index_bucket = ""
        mock_config.hyde_enabled = False
        mock_config.kb_reranker_model_arn = ""
        mock_config.kb_reranker_results = 10
        mock_config.anchor_retrieval_enabled = False
        mock_get_config.return_value = mock_config

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {"text": "Semantic only"},
                    "metadata": {
                        "x-amz-bedrock-kb-source-uri": "s3://bucket/docs/a.md",
                        "name": "Doc A",
                    },
                },
            ]
        }

        result = search_knowledge_base("test query", [])

        mock_bm25.assert_not_called()
        self.assertIn("Found 1 relevant document(s)", result)

    @patch("backend_orchestrator.tools.kb_retrieval.get_config")
    def test_no_kb_id_returns_error(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.knowledge_base_id = ""
        mock_get_config.return_value = mock_config

        result = search_knowledge_base("test", [])
        self.assertIn("Knowledge base not available", result)


class TestBuildRetrievalResponse(unittest.TestCase):
    def setUp(self):
        kb_retrieval._s3_client = None

    @patch("backend_orchestrator.tools.kb_retrieval._fetch_bm25_metadata")
    def test_bm25_only_hit_fetches_metadata(self, mock_fetch):
        mock_config = MagicMock()
        mock_config.bm25_index_bucket = "test-bucket"

        mock_fetch.return_value = {"name": "Fetched Name", "brochure_url": "https://example.com/doc.pdf"}

        results = [
            {
                "s3_key": "docs/bm25hit.md",
                "content": "BM25 content",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.5,
                "sources": {"bm25"},
            },
        ]

        response = _build_retrieval_response(results, mock_config, out_sources := [])
        mock_fetch.assert_called_once_with("docs/bm25hit.md", mock_config)
        self.assertIn("Found 1 relevant document(s)", response)

        self.assertEqual(out_sources[0]["brochureUrl"], "https://example.com/doc.pdf")

    def test_immutable_bm25_hit_uses_embedded_metadata_without_mutable_sidecar(self):
        """Rollback-safe release hits never consult a potentially newer docs/ sidecar."""
        mock_config = MagicMock()
        mock_config.bm25_index_bucket = "release-bucket"
        mock_config.retrieval_legacy_fallback = False
        mock_config.retrieval_release_id = f"sha256-{'a' * 64}"
        results = [
            {
                "s3_key": "docs/release.md",
                "content": "Immutable BM25 content",
                "metadata": {
                    "name": "Embedded Name",
                    "brochure_url": "https://example.com/immutable.pdf",
                },
                "source_uri": "",
                "rrf_score": 0.5,
                "sources": {"bm25"},
            },
        ]

        with (
            patch("backend_orchestrator.tools.kb_retrieval._fetch_bm25_metadata") as fetch_bm25,
            patch("backend_orchestrator.tools.kb_retrieval._fetch_s3_metadata_sidecar") as fetch_sidecar,
        ):
            _build_retrieval_response(results, mock_config, out_sources := [])

        fetch_bm25.assert_not_called()
        fetch_sidecar.assert_not_called()
        self.assertEqual(out_sources[0]["title"], "Embedded Name")
        self.assertEqual(out_sources[0]["retrievalReleaseId"], mock_config.retrieval_release_id)

    def test_bm25_hit_skips_metadata_when_no_bucket(self):
        mock_config = MagicMock()
        mock_config.bm25_index_bucket = ""

        results = [
            {
                "s3_key": "docs/hit.md",
                "content": "content",
                "metadata": {},
                "source_uri": "",
                "rrf_score": 0.5,
                "sources": {"bm25"},
            },
        ]

        response = _build_retrieval_response(results, mock_config, [])
        self.assertIn("Found 1 relevant document(s)", response)

    def test_semantic_hit_uses_existing_metadata(self):
        mock_config = MagicMock()
        mock_config.bm25_index_bucket = "test-bucket"

        results = [
            {
                "s3_key": "docs/sem.md",
                "content": "Semantic content",
                "metadata": {"name": "Original Name", "brochure_url": "https://original.com"},
                "source_uri": "s3://test-bucket/docs/sem.md",
                "rrf_score": 0.5,
                "sources": {"semantic"},
            },
        ]

        with patch("backend_orchestrator.tools.kb_retrieval._fetch_bm25_metadata") as mock_fetch:
            _build_retrieval_response(results, mock_config, [])
            mock_fetch.assert_not_called()

    def test_brochure_url_prefers_short_form(self):
        """brochure_url_short must surface as brochureUrl when both forms are in metadata."""
        mock_config = MagicMock()
        mock_config.bm25_index_bucket = "test-bucket"

        results = [
            {
                "s3_key": "docs/sem.md",
                "content": "Semantic content",
                "metadata": {
                    "name": "V0090",
                    "brochure_url": "https://www.deutsche-rentenversicherung.de/SharedDocs/Formulare/DE/_pdf/V0090.html",
                    "brochure_url_short": "https://www.deutsche-rentenversicherung.de/V0090",
                },
                "source_uri": "s3://test-bucket/docs/sem.md",
                "rrf_score": 0.5,
                "sources": {"semantic"},
            },
        ]

        response = _build_retrieval_response(results, mock_config, out_sources := [])
        self.assertIn("Found 1 relevant document(s)", response)
        self.assertEqual(out_sources[0]["brochureUrl"], "https://www.deutsche-rentenversicherung.de/V0090")

    def test_brochure_url_falls_back_to_long_form(self):
        mock_config = MagicMock()
        mock_config.bm25_index_bucket = "test-bucket"

        results = [
            {
                "s3_key": "docs/sem.md",
                "content": "Semantic content",
                "metadata": {"name": "B01", "brochure_url": "https://original.com"},
                "source_uri": "s3://test-bucket/docs/sem.md",
                "rrf_score": 0.5,
                "sources": {"semantic"},
            },
        ]

        response = _build_retrieval_response(results, mock_config, out_sources := [])
        self.assertIn("Found 1 relevant document(s)", response)
        self.assertEqual(out_sources[0]["brochureUrl"], "https://original.com")

    def test_offset_continues_numbering_after_seeded_sources(self):
        """Regression: `global_index = i` would collide appended sources with seeded [1..K] and
        silently mis-attribute follow-up cites. New KB results must continue at K+1."""
        mock_config = MagicMock()
        mock_config.bm25_index_bucket = ""

        seeds = [
            {"sourceIndex": 1, "title": "Seed A"},
            {"sourceIndex": 2, "title": "Seed B"},
        ]
        out_sources = list(seeds)
        results = [
            {
                "s3_key": "docs/new1.md",
                "content": "c1",
                "metadata": {"name": "New1", "brochure_url": "https://x/1"},
                "source_uri": "s3://b/docs/new1.md",
                "rrf_score": 0.5,
                "sources": {"semantic"},
            },
            {
                "s3_key": "docs/new2.md",
                "content": "c2",
                "metadata": {"name": "New2", "brochure_url": "https://x/2"},
                "source_uri": "s3://b/docs/new2.md",
                "rrf_score": 0.4,
                "sources": {"semantic"},
            },
        ]

        response = _build_retrieval_response(results, mock_config, out_sources)

        appended = out_sources[len(seeds) :]
        self.assertEqual([s["sourceIndex"] for s in appended], [3, 4])
        self.assertIn("[Source 3:", response)
        self.assertIn("[Source 4:", response)
        # Must not re-emit the seeds it was offset past.
        self.assertNotIn("[Source 1:", response)


class TestFilterByDomain(unittest.TestCase):
    """Domain demotion: cross-domain chunks are demoted, not dropped."""

    # FB01 = the Reha-Nachsorge brochure that carries rare terms like "IRENA"; B10 is an
    # in-domain "rente" brochure used as the competing chunk.
    _PRIORITY_MAP: ClassVar[dict] = {
        "FB01": {"prio": "E", "domain": "reha", "authority_boost": 1.25},
        "B10": {"prio": "S", "domain": "rente", "authority_boost": 2.0},
    }

    def setUp(self):
        """Inject a known priority map so _lookup_brochure resolves without hitting disk."""
        kb_retrieval._priority_map = dict(self._PRIORITY_MAP)

    def tearDown(self):
        kb_retrieval._priority_map = None

    @staticmethod
    def _reha_chunk(rrf_score: float) -> dict:
        return {
            "s3_key": "docs/318_Reha-Nachsorge/318_Reha-Nachsorge_0001.md",
            "content": "IRENA umfasst 24 Behandlungseinheiten ...",
            "metadata": {"brochure_number": "FB01"},
            "rrf_score": rrf_score,
            "sources": {"bm25"},
        }

    @staticmethod
    def _rente_chunk(rrf_score: float) -> dict:
        return {
            "s3_key": "docs/B10_Rente/B10_Rente_0000.md",
            "content": "Altersrente ...",
            "metadata": {"brochure_number": "B10"},
            "rrf_score": rrf_score,
            "sources": {"semantic"},
        }

    def _reha_in(self, results: list[dict]) -> bool:
        return any("318_Reha-Nachsorge" in r["s3_key"] for r in results)

    def test_strong_cross_domain_hit_survives_misclassification(self):
        """Regression: the old hard filter deleted this chunk entirely. A dominant BM25 hit
        (IRENA in a reha brochure) must survive a 'rente' misclassification."""
        results = [self._rente_chunk(2.0), self._reha_chunk(12.5)]

        filtered = _filter_by_domain(results, "rente")

        self.assertEqual(len(filtered), 2)
        self.assertTrue(self._reha_in(filtered))

        reha = next(r for r in filtered if "318_Reha-Nachsorge" in r["s3_key"])
        self.assertTrue(reha["cross_domain_penalized"])
        self.assertAlmostEqual(reha["rrf_score"], 12.5 * _CROSS_DOMAIN_PENALTY)
        # Even penalized (12.5 * 0.3 = 3.75) it still outranks the in-domain rente chunk (2.0).
        self.assertEqual(filtered[0]["s3_key"], reha["s3_key"])

    def test_weak_cross_domain_hit_is_demoted_below_in_domain(self):
        results = [self._reha_chunk(0.5), self._rente_chunk(2.0)]

        filtered = _filter_by_domain(results, "rente")

        self.assertEqual(len(filtered), 2)
        # In-domain rente chunk now ranks first; demoted reha chunk (0.5 * 0.3 = 0.15) is last.
        self.assertEqual(filtered[0]["s3_key"], "docs/B10_Rente/B10_Rente_0000.md")
        self.assertTrue(self._reha_in(filtered))

    def test_in_domain_chunks_are_untouched(self):
        results = [self._rente_chunk(2.0)]

        filtered = _filter_by_domain(results, "rente")

        self.assertEqual(filtered[0]["rrf_score"], 2.0)
        self.assertNotIn("cross_domain_penalized", filtered[0])

    def test_unknown_brochure_domain_is_not_penalized(self):
        """A chunk whose brochure is absent from the priority map is treated as in-domain."""
        unknown = {
            "s3_key": "docs/ZZ99_Unknown/ZZ99_Unknown_0000.md",
            "content": "...",
            "metadata": {"brochure_number": "ZZ99"},
            "rrf_score": 1.0,
            "sources": {"semantic"},
        }

        filtered = _filter_by_domain([unknown], "rente")

        self.assertEqual(filtered[0]["rrf_score"], 1.0)
        self.assertNotIn("cross_domain_penalized", filtered[0])

    def test_ambiguous_domain_skips_filtering_entirely(self):
        """mehrdeutig/sonstiges/themenfremd/None domains must leave every chunk untouched."""
        for domain in ("mehrdeutig", "sonstiges", "themenfremd", None):
            results = [self._reha_chunk(12.5), self._rente_chunk(2.0)]
            filtered = _filter_by_domain(results, domain)
            self.assertEqual(len(filtered), 2, msg=f"domain={domain}")
            self.assertFalse(any(r.get("cross_domain_penalized") for r in filtered), msg=f"domain={domain}")


class TestHasLexicalHit(unittest.TestCase):
    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    def test_returns_true_on_bm25_hit(self, mock_bm25):
        mock_bm25.return_value = [{"chunk_id": "docs/318_Reha/x.md", "score": 12.0, "content": "IRENA ..."}]
        self.assertTrue(_has_lexical_hit("IRENA", MagicMock(bm25_enabled=True)))

    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    def test_returns_false_when_no_bm25_hit(self, mock_bm25):
        mock_bm25.return_value = []
        self.assertFalse(_has_lexical_hit("Wetter", MagicMock(bm25_enabled=True)))

    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    def test_returns_false_when_bm25_disabled(self, mock_bm25):
        self.assertFalse(_has_lexical_hit("IRENA", MagicMock(bm25_enabled=False)))
        mock_bm25.assert_not_called()

    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    def test_returns_false_on_bm25_error(self, mock_bm25):
        mock_bm25.side_effect = Exception("index unavailable")
        self.assertFalse(_has_lexical_hit("IRENA", MagicMock(bm25_enabled=True)))


class TestThemenfremdSearchFirst(unittest.TestCase):
    """A 'themenfremd' classification must search first and only refuse without a hit."""

    def setUp(self):
        kb_retrieval._bedrock_client = None
        kb_retrieval._s3_client = None
        kb_retrieval._priority_map = None

    @staticmethod
    def _config() -> MagicMock:
        cfg = MagicMock()
        cfg.knowledge_base_id = "kb-123"
        cfg.hyde_enabled = False
        cfg.bm25_enabled = True
        cfg.bm25_index_bucket = "test-bucket"
        return cfg

    @patch("backend_orchestrator.tools.kb_retrieval._apply_final_reranking", side_effect=lambda r, q, c: r)
    @patch("backend_orchestrator.tools.kb_retrieval._perform_search_and_enhancement")
    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    @patch("backend_orchestrator.tools.kb_retrieval.get_config")
    def test_themenfremd_with_lexical_hit_returns_results(self, mock_get_config, mock_bm25, mock_perform, _mock_rerank):
        """A mislabeled DRV term (IRENA) is rescued when BM25 has a hit."""
        mock_get_config.return_value = self._config()
        mock_bm25.return_value = [{"chunk_id": "docs/318_Reha/x.md", "score": 12.0, "content": "IRENA ..."}]
        mock_perform.return_value = [
            {
                "s3_key": "docs/318_Reha-Nachsorge/318_Reha-Nachsorge_0001.md",
                "content": "IRENA umfasst 24 Behandlungseinheiten ...",
                "metadata": {"brochure_number": "FB01", "name": "Reha-Nachsorge"},
                "rrf_score": 5.0,
                "sources": {"bm25"},
            }
        ]

        result = search_knowledge_base("IRENA", out_sources := [], domain="themenfremd")

        mock_perform.assert_called_once()
        self.assertIn("Found 1 relevant document(s)", result)
        self.assertNotEqual(result, _OUT_OF_SCOPE_MESSAGE)
        self.assertEqual(len(out_sources), 1)

    @patch("backend_orchestrator.tools.kb_retrieval._apply_final_reranking", side_effect=lambda r, q, c: r)
    @patch("backend_orchestrator.tools.kb_retrieval._perform_search_and_enhancement")
    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    @patch("backend_orchestrator.tools.kb_retrieval.get_config")
    def test_themenfremd_without_lexical_hit_refuses_without_semantic_search(
        self, mock_get_config, mock_bm25, mock_perform, _mock_rerank
    ):
        """Genuinely off-topic: BM25 probe misses, so refuse without the costly semantic search."""
        mock_get_config.return_value = self._config()
        mock_bm25.return_value = []

        result = search_knowledge_base("Wie ist das Wetter?", out_sources := [], domain="themenfremd")

        mock_bm25.assert_called_once()
        mock_perform.assert_not_called()
        self.assertEqual(result, _OUT_OF_SCOPE_MESSAGE)
        self.assertEqual(out_sources, [])


class TestIsRareTermQuery(unittest.TestCase):
    """Rare-term detection must be hyphen-insensitive (IRENA family + others)."""

    def test_unhyphenated_rena_acronyms_match(self):
        """Regression: these silently missed before because the set only held hyphenated forms."""
        for q in ("IRENA", "Was ist IRENA?", "TRENA", "PsyRENA"):
            self.assertTrue(_is_rare_term_query(q), msg=q)

    def test_hyphenated_rena_acronyms_still_match(self):
        for q in ("I-RENA", "T-RENA", "Psy-RENA"):
            self.assertTrue(_is_rare_term_query(q), msg=q)

    def test_other_rare_terms_match(self):
        for q in ("Frage zur Knappschaft", "Flexirente Voraussetzungen", "Riester Förderung"):
            self.assertTrue(_is_rare_term_query(q), msg=q)

    def test_non_rare_query_does_not_match(self):
        self.assertFalse(_is_rare_term_query("Wie hoch ist meine Altersrente?"))

    def test_sucht_matches_only_at_word_start(self):
        for q in ("Sucht", "Suchtberatung", "Was ist eine Suchtreha?"):
            self.assertTrue(_is_rare_term_query(q), msg=q)
        # Regression: everyday verbs ending in -sucht must NOT trigger the rare-term boost.
        for q in ("Ich habe das Thema untersucht", "Ich habe nach Reha gesucht", "Antrag besucht", "Ich versuchte es"):
            self.assertFalse(_is_rare_term_query(q), msg=q)


class TestExtractBrochureNumber(unittest.TestCase):
    """Brochure folder (second-to-last segment) is the source, not the 'docs' prefix."""

    def test_reads_folder_under_docs_prefix(self):
        """Regression: split("/")[0] returned "docs" and never matched."""
        self.assertEqual(_extract_brochure_number("docs/B02_Name/B02_Name_0001.md"), "B02")

    def test_reads_folder_without_prefix(self):
        self.assertEqual(_extract_brochure_number("B40_Name/B40_Name_0000.md"), "B40")

    def test_normalizes_alt_prefix(self):
        self.assertEqual(_extract_brochure_number("docs/ALT_B16_Foo/ALT_B16_Foo_0001.md"), "ALT-B16")

    def test_bare_folder_without_slash(self):
        self.assertEqual(_extract_brochure_number("B40_Name"), "B40")

    def test_numeric_gliederungsnummer_folder_returns_empty(self):
        """Numeric folders carry no brochure code; brochure_number metadata is authoritative."""
        self.assertEqual(_extract_brochure_number("docs/318_Reha-Nachsorge/318_Reha-Nachsorge_0001.md"), "")


class TestExtractQueryYears(unittest.TestCase):
    def test_extracts_single_year(self):
        self.assertEqual(_extract_query_years("Ich bin 1963 geboren"), {"1963"})

    def test_extracts_multiple_years(self):
        self.assertEqual(_extract_query_years("zwischen 1958 und 2024"), {"1958", "2024"})

    def test_ignores_non_year_numbers(self):
        """63 (Rente mit 63) and 45 (Beitragsjahre) are not 4-digit years."""
        self.assertEqual(_extract_query_years("Rente mit 63 nach 45 Jahren"), set())

    def test_no_year_returns_empty(self):
        self.assertEqual(_extract_query_years("Wie hoch ist meine Altersrente?"), set())

    def test_expands_two_digit_birth_year(self):
        """Colloquial forms the rephrase keeps only in the original question all mean 1963."""
        for q in ("Ich bin 63 geboren", "Jahrgang 63", "Ich bin Jahrgang 63 geboren", "geboren 63", "Baujahr 63"):
            self.assertEqual(_extract_query_years(q), {"1963"}, msg=q)

    def test_two_digit_age_without_birth_keyword_is_ignored(self):
        """No birth keyword, no expansion: these are AGEs, not birth years."""
        self.assertEqual(_extract_query_years("ich bin 61, wann kann ich in Rente gehen"), set())
        self.assertEqual(_extract_query_years("möchte mit 63 in Rente"), set())

    def test_four_digit_year_is_not_mis_expanded(self):
        """The two-digit rule must not fire on a sub-string of a real four-digit year."""
        self.assertEqual(_extract_query_years("Jahrgang 2005"), {"2005"})
        self.assertEqual(_extract_query_years("1963 geboren"), {"1963"})


class TestApplyYearMatchBoost(unittest.TestCase):
    """Regression guard: the per-cohort table (carries "1963") must out-rank the generic
    "Mindestalter 63" overview chunk (no birth year), which the model otherwise anchors on."""

    @staticmethod
    def _chunk(key: str, content: str, rrf_score: float) -> dict:
        return {"s3_key": key, "content": content, "rrf_score": rrf_score}

    def test_year_chunk_is_boosted_and_reordered_above_overview(self):
        # Overview starts higher (0.0164) than the cohort table (0.0149), as in production.
        overview = self._chunk("checklist", "Mindestalter 63, Anhebung auf 65 ab Jahrgang 1953", 0.0164)
        cohort = self._chunk("table", "| 1963 | 22 | 66 | 10 | 13,8 |", 0.0149)

        boosted = _apply_year_match_boost([overview, cohort], "Rente mit 63 Jahrgang 1963")

        # Cohort table now leads: 0.0149 * 1.5 = 0.02235 > 0.0164.
        self.assertEqual(boosted[0]["s3_key"], "table")
        self.assertTrue(boosted[0]["year_match_boosted"])
        self.assertAlmostEqual(boosted[0]["rrf_score"], 0.0149 * _YEAR_MATCH_BOOST)

    def test_non_matching_chunk_is_untouched(self):
        overview = self._chunk("checklist", "Mindestalter 63", 0.0164)

        boosted = _apply_year_match_boost([overview], "Jahrgang 1963")

        self.assertEqual(boosted[0]["rrf_score"], 0.0164)
        self.assertNotIn("year_match_boosted", boosted[0])

    def test_no_year_in_query_is_noop(self):
        results = [self._chunk("a", "enthält 1963", 1.0), self._chunk("b", "kein Jahr", 2.0)]

        boosted = _apply_year_match_boost(results, "Wie hoch ist meine Rente?")

        self.assertEqual([r["s3_key"] for r in boosted], ["a", "b"])
        self.assertEqual(boosted[0]["rrf_score"], 1.0)
        self.assertFalse(any(r.get("year_match_boosted") for r in boosted))

    def test_falls_back_to_score_when_no_rrf_score(self):
        chunk = {"s3_key": "x", "content": "Jahrgang 1963", "score": 2.0}

        boosted = _apply_year_match_boost([chunk], "1963")

        self.assertAlmostEqual(boosted[0]["rrf_score"], 2.0 * _YEAR_MATCH_BOOST)

    def test_year_recovered_from_original_question_when_rephrase_dropped_it(self):
        """Real failure: rephrased search query lost the birth year, but the original question
        still carries it. The boost must fire off the latter."""
        overview = self._chunk("checklist", "Mindestalter 63, Anhebung auf 65", 0.0164)
        cohort = self._chunk("table", "| 1963 | 22 | 64 | 10 |", 0.0149)

        boosted = _apply_year_match_boost(
            [overview, cohort],
            "Rente mit 63 Voraussetzungen 45 Versicherungsjahre",
            "Ich bin Jahrgang 63 geboren und möchte die Rente mit 63",
        )

        self.assertEqual(boosted[0]["s3_key"], "table")
        self.assertTrue(boosted[0]["year_match_boosted"])


class TestKeywordPhraseMatches(unittest.TestCase):
    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(kb_retrieval._WORD_RE.findall(text.lower()))

    def test_multi_token_phrase_matches_when_all_tokens_present(self):
        q = self._tokens("Kann ich rückwirkend freiwillige Beiträge bezahlen?")
        self.assertEqual(_keyword_phrase_matches(q, "freiwillige Versicherung, freiwillige Beiträge"), 1)

    def test_no_match_for_unrelated_keywords(self):
        q = self._tokens("Kann ich rückwirkend freiwillige Beiträge bezahlen?")
        self.assertEqual(_keyword_phrase_matches(q, "Kindererziehungszeiten, Berücksichtigungszeiten, Mütterrente"), 0)

    def test_generic_short_single_token_does_not_trigger(self):
        """A lone single token must be specific (>=8 chars) to route."""
        q = self._tokens("Wie hoch ist die Rente?")
        self.assertEqual(_keyword_phrase_matches(q, "Rente"), 0)

    def test_single_token_boundary_at_8_chars(self):
        """Boundary on the len>=8 rule: 7 chars does not route, 8 chars does."""
        self.assertEqual(_keyword_phrase_matches({"beitrag"}, "beitrag"), 0)
        self.assertEqual(_keyword_phrase_matches({"beitraege"}, "beitraege"), 1)

    def test_empty_keywords(self):
        self.assertEqual(_keyword_phrase_matches({"freiwillige"}, ""), 0)


class TestRouteTargetBrochure(unittest.TestCase):
    """Keyword routing picks the unambiguous on-target brochure (and abstains otherwise)."""

    @staticmethod
    def _config(min_matches: int = 1, max_tied: int = 2) -> MagicMock:
        cfg = MagicMock()
        cfg.metadata_routing_min_matches = min_matches
        cfg.metadata_routing_max_tied = max_tied
        return cfg

    @staticmethod
    def _result(brochure: str, primary_keywords: str) -> dict:
        return {
            "s3_key": f"docs/{brochure}/c.md",
            "metadata": {"brochure_number": brochure, "primary_keywords": primary_keywords},
        }

    def test_clear_winner_routes(self):
        results = [
            self._result("B26", "freiwillige Versicherung, freiwillige Beiträge"),
            self._result("F01", "Kindererziehungszeiten, Mütterrente"),
        ]
        self.assertEqual(
            _route_target_brochure(results, "rückwirkend freiwillige Beiträge bezahlen", self._config()), "B26"
        )

    def test_no_match_abstains(self):
        results = [self._result("F01", "Kindererziehungszeiten, Mütterrente")]
        self.assertIsNone(_route_target_brochure(results, "rückwirkend freiwillige Beiträge bezahlen", self._config()))

    def test_two_way_tie_is_broken_by_retrieval_rank(self):
        """Regression: a 1-1 tie used to abstain. Keyword score and retrieval rank are
        independent signals, so the better-ranked one wins."""
        results = [
            self._result("B26", "freiwillige Beiträge"),
            self._result("V0062", "freiwillige Beiträge"),
        ]
        self.assertEqual(_route_target_brochure(results, "freiwillige Beiträge zahlen", self._config()), "B26")

    def test_tie_break_follows_retrieval_order_not_argument_order(self):
        """The winner must be whichever brochure the retriever ranked first, not a fixed name."""
        results = [
            self._result("V0062", "freiwillige Beiträge"),
            self._result("B26", "freiwillige Beiträge"),
        ]
        self.assertEqual(_route_target_brochure(results, "freiwillige Beiträge zahlen", self._config()), "V0062")

    def test_wide_tie_still_abstains(self):
        """Three-way tie is real ambiguity, not a coin-flip — routing stays a no-op."""
        results = [
            self._result("B26", "freiwillige Beiträge"),
            self._result("V0062", "freiwillige Beiträge"),
            self._result("B10", "freiwillige Beiträge"),
        ]
        self.assertIsNone(_route_target_brochure(results, "freiwillige Beiträge zahlen", self._config()))

    def test_max_tied_one_restores_strict_behaviour(self):
        """The config lever is the no-deploy rollback: max_tied=1 is the old strict rule."""
        results = [
            self._result("B26", "freiwillige Beiträge"),
            self._result("V0062", "freiwillige Beiträge"),
        ]
        self.assertIsNone(_route_target_brochure(results, "freiwillige Beiträge zahlen", self._config(max_tied=1)))

    def test_zero_score_tie_never_routes(self):
        """A tie at zero matches is not evidence — min_matches must still gate it."""
        results = [
            self._result("B26", "Kindererziehungszeiten"),
            self._result("V0062", "Mütterrente"),
        ]
        self.assertIsNone(_route_target_brochure(results, "Rente mit 60 Voraussetzungen", self._config()))


class TestMergeScopedResults(unittest.TestCase):
    """Scoped (brochure-filtered) hits must union into the pool without duplicating by s3_key."""

    def test_dedup_by_s3_key(self):
        pool = [{"s3_key": "docs/B26/_0007.md", "content": "a"}]
        scoped = [
            {"s3_key": "docs/B26/_0007.md", "content": "dup"},
            {"s3_key": "docs/B26/_0009.md", "content": "Nachzahlen erlaubt"},
        ]
        merged = _merge_scoped_results(pool, scoped)
        keys = [r["s3_key"] for r in merged]
        self.assertEqual(keys, ["docs/B26/_0007.md", "docs/B26/_0009.md"])

    def test_empty_scoped_is_noop(self):
        pool = [{"s3_key": "docs/B26/_0007.md"}]
        self.assertEqual(_merge_scoped_results(pool, []), pool)


class TestPerformSearchRoutingIntegration(unittest.TestCase):
    """Covers wiring guarantees the routing helpers cannot: (a) the scoped brochure search runs
    and is unioned in, (b) the main search is NEVER narrowed (no brochure_filter), (c) a failing
    scoped search cannot break the main path. The feature ships default-on, so a regression
    here would be silent."""

    def setUp(self):
        """Inject an empty priority map so authority boost resolves without hitting disk."""
        kb_retrieval._priority_map = {}

    def tearDown(self):
        kb_retrieval._priority_map = None

    @staticmethod
    def _config(routing_enabled: bool = True) -> MagicMock:
        cfg = MagicMock()
        cfg.metadata_routing_enabled = routing_enabled
        cfg.metadata_routing_results = 15
        cfg.metadata_routing_min_matches = 1
        cfg.metadata_routing_max_tied = 2
        cfg.bm25_enabled = False
        cfg.anchor_retrieval_enabled = False
        cfg.bm25_index_bucket = ""
        cfg.kb_retrieval_results = 50
        return cfg

    @staticmethod
    def _hit(s3_key: str, content: str, score: float = 0.5) -> dict:
        return {
            "s3_key": s3_key,
            "content": content,
            "metadata": {"brochure_number": "B26", "primary_keywords": "freiwillige Beiträge"},
            "source_uri": f"s3://b/{s3_key}",
            "score": score,
        }

    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    @patch("backend_orchestrator.tools.kb_retrieval._semantic_search")
    def test_routing_unions_scoped_hits_and_never_narrows_main_search(self, mock_semantic, mock_bm25):
        main_hit = self._hit("docs/B26/_0001.md", "global overview", 0.9)
        scoped_hit = self._hit("docs/B26/_0009.md", "Nachzahlen erlaubt", 0.4)
        # 1st call = global (no filter); 2nd call = brochure-scoped.
        mock_semantic.side_effect = [[main_hit], [scoped_hit]]

        out = kb_retrieval._perform_search_and_enhancement(
            "rückwirkend freiwillige Beiträge bezahlen",
            "freiwillige beiträge nachzahlung",
            self._config(),
            "rente",
            "",
        )

        keys = {r["s3_key"] for r in out}
        self.assertIn("docs/B26/_0009.md", keys)
        self.assertIn("docs/B26/_0001.md", keys)

        self.assertEqual(mock_semantic.call_count, 2)
        # Main (first) search must carry NO brochure_filter; only the scoped (second) call is
        # filtered to the target brochure.
        self.assertIsNone(mock_semantic.call_args_list[0].kwargs.get("brochure_filter"))
        self.assertEqual(mock_semantic.call_args_list[1].kwargs.get("brochure_filter"), "B26")

    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    @patch("backend_orchestrator.tools.kb_retrieval._semantic_search")
    def test_scoped_search_failure_leaves_global_results_intact(self, mock_semantic, mock_bm25):
        main_hit = self._hit("docs/B26/_0001.md", "global overview", 0.9)
        mock_semantic.side_effect = [[main_hit], Exception("scoped retrieve boom")]

        out = kb_retrieval._perform_search_and_enhancement(
            "rückwirkend freiwillige Beiträge bezahlen",
            "freiwillige beiträge nachzahlung",
            self._config(),
            "rente",
            "",
        )

        keys = {r["s3_key"] for r in out}
        self.assertIn("docs/B26/_0001.md", keys)

    @patch("backend_orchestrator.tools.kb_retrieval.bm25_search")
    @patch("backend_orchestrator.tools.kb_retrieval._semantic_search")
    def test_routing_disabled_runs_only_unscoped_search(self, mock_semantic, mock_bm25):
        main_hit = self._hit("docs/B26/_0001.md", "global overview", 0.9)
        mock_semantic.side_effect = [[main_hit]]

        kb_retrieval._perform_search_and_enhancement(
            "rückwirkend freiwillige Beiträge bezahlen",
            "freiwillige beiträge nachzahlung",
            self._config(routing_enabled=False),
            "rente",
            "",
        )

        self.assertEqual(mock_semantic.call_count, 1)
        self.assertIsNone(mock_semantic.call_args_list[0].kwargs.get("brochure_filter"))


class TestMerkblattDomainPenalty(unittest.TestCase):
    """Domain penalty/boost behavior with Merkblatt domains."""

    _PRIORITY_MAP: ClassVar[dict] = {
        "V0017": {"prio": "A", "domain": "Versicherung", "authority_boost": 1.2},
        "B34": {"prio": "S", "domain": "Versicherung", "authority_boost": 1.25},
    }

    def setUp(self):
        kb_retrieval._priority_map = dict(self._PRIORITY_MAP)

    def tearDown(self):
        kb_retrieval._priority_map = None

    @staticmethod
    def _merkblatt_chunk(rrf_score: float) -> dict:
        return {
            "s3_key": "docs/V0017/V0017_0000.md",
            "content": "Befreiung von der Versicherungspflicht ...",
            "metadata": {"brochure_number": "V0017"},
            "rrf_score": rrf_score,
            "sources": {"bm25"},
        }

    def test_merkblatt_not_penalized_when_domain_matches(self):
        results = [self._merkblatt_chunk(5.0)]

        filtered = _filter_by_domain(results, "versicherung")

        self.assertEqual(filtered[0]["rrf_score"], 5.0)
        self.assertNotIn("cross_domain_penalized", filtered[0])

    def test_merkblatt_penalized_when_domain_mismatches(self):
        """Merkblatt with domain=Versicherung gets 0.3x penalty for query domain 'rente'."""
        results = [self._merkblatt_chunk(5.0)]

        filtered = _filter_by_domain(results, "rente")

        self.assertAlmostEqual(filtered[0]["rrf_score"], 5.0 * _CROSS_DOMAIN_PENALTY)
        self.assertTrue(filtered[0]["cross_domain_penalized"])


if __name__ == "__main__":
    unittest.main()
