"""Tests for deterministic content / parent-subdocument dedup after fusion & rerank (#698)."""

import copy
import hashlib
import unittest
from types import SimpleNamespace

from backend_orchestrator.tools.kb_retrieval import (
    _bucket_key,
    _build_retrieval_response,
    _containment,
    _deduplicate_overlapping_results,
    _exact_content_hash,
    _hash_gram,
    _is_focused_chunk,
    _normalize_for_overlap,
    _overlap_signature,
    _shingle_set,
)

# A contiguous ~10-token "table" body shared verbatim by a parent chunk and its extracted copy.
_TABLE: str = "einkommen aus vermietung wird zur haelfte auf die grundsicherung angerechnet"
_INTRO: str = "die grundsicherung im alter sichert den lebensunterhalt fuer aeltere menschen mit sehr geringem"
_FAQ: str = "haeufige fragen zum antrag auf leistungen werden hier ausfuehrlich und verstaendlich beantwortet"


def _config(**overrides) -> SimpleNamespace:
    """Build a dedup config double with the documented defaults, overridable per test."""
    values = {
        "content_dedup_enabled": True,
        "content_dedup_containment_min": 0.80,
        "content_dedup_parent_context_min": 0.50,
        "content_dedup_shingle_size": 8,
        # Only consulted by _build_retrieval_response in the citation test below.
        "bm25_index_bucket": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _result(
    s3_key: str,
    content: str,
    *,
    brochure_number: str | None = "B01",
    chunk_type: str | None = None,
    rrf_score: float = 0.5,
    sources: set[str] | None = None,
    is_golden: bool = False,
    extra_metadata: dict | None = None,
    source_uri: str = "",
) -> dict:
    """Build a retrieval result dict shaped like the ones reaching the dedup pass."""
    metadata: dict = {}
    if brochure_number is not None:
        metadata["brochure_number"] = brochure_number
    if chunk_type is not None:
        metadata["chunk_type"] = chunk_type
    if extra_metadata:
        metadata.update(extra_metadata)
    result = {
        "s3_key": s3_key,
        "content": content,
        "metadata": metadata,
        "rrf_score": rrf_score,
        "sources": set(sources or {"semantic"}),
        "source_uri": source_uri,
    }
    if is_golden:
        result["is_golden_chunk"] = True
    return result


class TestOverlapPrimitives(unittest.TestCase):
    def test_normalize_strips_front_matter_and_markdown(self):
        text = "---\nbrochure_number: B02\n---\n## Titel\n| Rente | 1200 |\n- *wichtig*"
        tokens = _normalize_for_overlap(text)
        self.assertNotIn("brochure_number", tokens)
        self.assertNotIn("b02", tokens)
        self.assertEqual(tokens, ["titel", "rente", "1200", "wichtig"])

    def test_normalize_casefolds(self):
        self.assertEqual(_normalize_for_overlap("Rente GRUNDSICHERUNG"), ["rente", "grundsicherung"])

    def test_normalize_empty(self):
        self.assertEqual(_normalize_for_overlap(""), [])
        self.assertEqual(_normalize_for_overlap("   \n  "), [])

    def test_hash_gram_is_blake2b_not_builtin_hash(self):
        """Determinism: must be stable blake2b, never per-process-salted builtin hash()."""
        expected = int.from_bytes(hashlib.blake2b(b"a b c", digest_size=8).digest(), "big")
        self.assertEqual(_hash_gram("a b c"), expected)
        self.assertEqual(_hash_gram("a b c"), _hash_gram("a b c"))

    def test_shingle_unigram_fallback_below_size(self):
        tokens = ["antrag", "rechtzeitig", "stellen"]  # 3 < shingle_size 8
        sig = _shingle_set(tokens, 8)
        self.assertEqual(sig, frozenset(_hash_gram(t) for t in tokens))

    def test_shingle_ngrams_at_or_above_size(self):
        tokens = _TABLE.split()  # 10 tokens
        sig = _shingle_set(tokens, 8)
        self.assertEqual(len(sig), len(tokens) - 8 + 1)  # 3 windows

    def test_containment_subset_is_one(self):
        a = frozenset({1, 2, 3})
        b = frozenset({1, 2, 3, 4, 5})
        self.assertEqual(_containment(a, b), 1.0)  # smaller fully contained
        self.assertEqual(_containment(frozenset(), b), 0.0)

    def test_overlap_signature_is_cached_on_result(self):
        result = _result("docs/B01/x.md", _TABLE)
        first = _overlap_signature(result, 8)
        self.assertIs(result["_overlap_signature"], first)
        self.assertIs(_overlap_signature(result, 8), first)

    def test_is_focused_chunk(self):
        self.assertTrue(_is_focused_chunk(_result("k", "c", chunk_type="table")))
        self.assertTrue(_is_focused_chunk(_result("k", "c", chunk_type="note")))
        self.assertFalse(_is_focused_chunk(_result("k", "c")))

    def test_bucket_key_is_brochure_number(self):
        self.assertEqual(_bucket_key(_result("k", "c", brochure_number="B07")), "B07")
        self.assertEqual(_bucket_key(_result("k", "c", brochure_number=None)), "")

    def test_exact_content_hash_none_for_empty(self):
        self.assertIsNone(_exact_content_hash(_result("k", "   ")))
        self.assertIsNotNone(_exact_content_hash(_result("k", _TABLE)))


class TestDeduplicateOverlappingResults(unittest.TestCase):
    def test_exact_parent_subdoc_dup_golden_parent(self):
        """Table-dominated golden parent + its extracted table copy → one survivor."""
        parent = _result(
            "docs/B01/B01_0000.md", _TABLE + " tabelle", sources={"semantic"}, rrf_score=0.6, is_golden=True
        )
        focused = _result(
            "docs/B01_table_000/B01_table_000_0000.md",
            _TABLE,
            chunk_type="table",
            sources={"bm25"},
            rrf_score=0.4,
        )

        out = _deduplicate_overlapping_results([parent, focused], _config())

        self.assertEqual(len(out), 1)
        survivor = out[0]
        self.assertEqual(survivor["s3_key"], "docs/B01/B01_0000.md")  # golden parent kept
        self.assertEqual(survivor["sources"], {"semantic", "bm25"})  # sources unioned
        self.assertEqual(len(survivor["deduplicated_from"]), 1)
        trail = survivor["deduplicated_from"][0]
        self.assertEqual(trail["s3_key"], "docs/B01_table_000/B01_table_000_0000.md")
        self.assertEqual(trail["chunk_type"], "table")
        self.assertEqual(trail["rule"], "golden")
        self.assertEqual(trail["containment"], 1.0)

    def test_partial_overlap_keeps_broad_parent(self):
        """Focused table fully inside a broad parent (>=50% unique) → parent kept."""
        parent = _result("docs/B01/B01_0000.md", f"{_INTRO} {_TABLE} {_FAQ}", rrf_score=0.5)
        focused = _result("docs/B01_table_000/x.md", _TABLE, chunk_type="table", rrf_score=0.5)

        out = _deduplicate_overlapping_results([parent, focused], _config())

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["s3_key"], "docs/B01/B01_0000.md")  # broad parent survives
        self.assertEqual(out[0]["deduplicated_from"][0]["rule"], "parent_context")
        self.assertGreaterEqual(out[0]["deduplicated_from"][0]["parent_unique_ratio"], 0.5)

    def test_distinct_passages_same_brochure_both_kept(self):
        """Two genuinely different passages from one brochure are not collapsed."""
        parent = _result(
            "docs/B01/B01_0000.md",
            "beitragszeiten werden fuer die rente angerechnet wenn pflichtbeitraege regelmaessig gezahlt wurden",
        )
        note = _result(
            "docs/B01_note_000/x.md",
            "unser tipp stellen sie den antrag rechtzeitig vor dem geplanten rentenbeginn beim traeger",
            chunk_type="note",
        )

        out = _deduplicate_overlapping_results([parent, note], _config())

        self.assertEqual(len(out), 2)
        self.assertNotIn("deduplicated_from", out[0])
        self.assertNotIn("deduplicated_from", out[1])

    def test_semantic_bm25_same_content_different_key_form(self):
        """Identical content under s3_key vs chunk_id key form collapses globally despite different buckets."""
        content = "die altersrente kann fruehestens mit erreichen der regelaltersgrenze abschlagsfrei bezogen werden"
        semantic = _result("docs/B02/B02_0000.md", content, brochure_number="B02", sources={"semantic"}, rrf_score=0.9)
        bm25 = _result("B02/B02_0000.md", content, brochure_number=None, sources={"bm25"}, rrf_score=0.4)

        out = _deduplicate_overlapping_results([semantic, bm25], _config())

        self.assertEqual(len(out), 1)
        survivor = out[0]
        self.assertEqual(survivor["sources"], {"semantic", "bm25"})
        self.assertEqual(survivor["s3_key"], "docs/B02/B02_0000.md")  # higher rrf_score wins
        self.assertEqual(survivor["rrf_score"], 0.9)
        self.assertEqual(survivor["deduplicated_from"][0]["containment"], 1.0)

    def test_deterministic_across_repeated_runs(self):
        """Identical input yields identical survivor order and keys every run."""
        base = [
            _result("docs/B01/B01_0000.md", _TABLE + " tabelle", is_golden=True, sources={"semantic"}),
            _result("docs/B01_distinct/x.md", f"{_INTRO} andere passage ueber wohngeld und mietzuschuss regeln"),
            _result("docs/B01_table_000/x.md", _TABLE, chunk_type="table", sources={"bm25"}),
            _result("docs/B02/B02_0000.md", "voellig anderes thema ueber rehabilitation und nachsorge im detail"),
        ]

        first = _deduplicate_overlapping_results(copy.deepcopy(base), _config())
        second = _deduplicate_overlapping_results(copy.deepcopy(base), _config())

        self.assertEqual([r["s3_key"] for r in first], [r["s3_key"] for r in second])
        self.assertEqual(len(first), 3)  # the table copy collapsed into the golden parent

    def test_golden_guard_overrides_prefer_focused(self):
        """Golden guard keeps a golden parent even where 'prefer focused' would otherwise win."""
        golden_parent = _result("docs/B01/B01_0000.md", _TABLE + " tabelle", is_golden=True)
        focused = _result("docs/B01_table_000/x.md", _TABLE, chunk_type="table")

        out = _deduplicate_overlapping_results([golden_parent, focused], _config())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["s3_key"], "docs/B01/B01_0000.md")
        self.assertTrue(out[0]["is_golden_chunk"])
        self.assertEqual(out[0]["deduplicated_from"][0]["rule"], "golden")

    def test_prefer_focused_when_no_golden_and_parent_not_context_rich(self):
        """Without a golden member, the focused note/table is the higher-signal keeper."""
        parent = _result("docs/B01/B01_0000.md", _TABLE + " tabelle")
        focused = _result("docs/B01_table_000/x.md", _TABLE, chunk_type="table")

        out = _deduplicate_overlapping_results([parent, focused], _config())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["s3_key"], "docs/B01_table_000/x.md")  # focused survives
        self.assertEqual(out[0]["deduplicated_from"][0]["rule"], "prefer_focused")

    def test_unigram_path_short_note_prefers_focused(self):
        """Content shorter than shingle_size uses the unigram fallback and still collapses."""
        parent = _result("docs/B01/B01_0000.md", "antrag rechtzeitig stellen beim traeger")
        note = _result("docs/B01_note_000/x.md", "antrag rechtzeitig stellen", chunk_type="note")

        out = _deduplicate_overlapping_results([parent, note], _config())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["s3_key"], "docs/B01_note_000/x.md")
        self.assertEqual(out[0]["deduplicated_from"][0]["rule"], "prefer_focused")

    def test_empty_content_never_collapses(self):
        """Empty/whitespace content has an empty signature → never collapses."""
        a = _result("docs/B01/a.md", "")
        b = _result("docs/B01/b.md", "   \n  ")
        out = _deduplicate_overlapping_results([a, b], _config())
        self.assertEqual(len(out), 2)

    def test_disabled_flag_is_noop(self):
        """Feature flag off returns the input unchanged, even with an exact duplicate."""
        dup_a = _result("docs/B01/a.md", _TABLE, sources={"semantic"})
        dup_b = _result("docs/B01/b.md", _TABLE, sources={"bm25"})
        results = [dup_a, dup_b]

        out = _deduplicate_overlapping_results(results, _config(content_dedup_enabled=False))

        self.assertIs(out, results)
        self.assertEqual(len(out), 2)
        self.assertNotIn("deduplicated_from", out[0])

    def test_single_result_is_noop(self):
        single = [_result("docs/B01/a.md", _TABLE)]
        self.assertEqual(len(_deduplicate_overlapping_results(single, _config())), 1)

    def test_different_brochures_not_collapsed_by_containment(self):
        """Bucketing guard: overlapping chunks in different brochures stay separate."""
        a = _result("docs/B01/x.md", f"{_TABLE} zusatz eins", brochure_number="B01")
        b = _result("docs/B99/y.md", f"{_TABLE} zusatz zwei", brochure_number="B99")
        out = _deduplicate_overlapping_results([a, b], _config())
        self.assertEqual(len(out), 2)


class TestDedupCitationAndScore(unittest.TestCase):
    def test_survivor_metadata_and_max_score_reach_response(self):
        parent = _result(
            "docs/B01/B01_0000.md",
            f"{_INTRO} {_TABLE} {_FAQ}",
            rrf_score=0.5,
            extra_metadata={"name": "Grundsicherung", "brochure_url": "https://example.de/gs"},
            source_uri="s3://bucket/docs/B01/B01_0000.md",
        )
        focused = _result("docs/B01_table_000/x.md", _TABLE, chunk_type="table", rrf_score=0.9, sources={"bm25"})

        deduped = _deduplicate_overlapping_results([parent, focused], _config())
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["rrf_score"], 0.9)  # max of the pair

        out_sources: list[dict] = []
        response = _build_retrieval_response(deduped, _config(), out_sources)

        self.assertIn("Found 1 relevant document(s)", response)
        self.assertEqual(len(out_sources), 1)
        self.assertEqual(out_sources[0]["title"], "Grundsicherung")
        self.assertEqual(out_sources[0]["brochureUrl"], "https://example.de/gs")
        # Provenance stays internal — must not leak into the client-facing source dict.
        self.assertNotIn("deduplicated_from", out_sources[0])
        self.assertFalse(any("B01_table_000" in (s.get("documentId") or "") for s in out_sources))


if __name__ == "__main__":
    unittest.main()
