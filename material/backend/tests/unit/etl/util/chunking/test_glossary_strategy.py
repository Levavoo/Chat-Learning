
import pytest

from etl.util.chunking.glossary_strategy import GlossaryChunkingStrategy


class TestGlossaryChunkingStrategyChunk:

    @pytest.fixture
    def strategy(self):
        return GlossaryChunkingStrategy()

    def test_extracts_term_definition_pairs(self, strategy, glossary_content, base_metadata):
        chunks = strategy.chunk(glossary_content, base_metadata)
        assert len(chunks) == 3

    def test_chunk_type_is_glossary_entry(self, strategy, glossary_content, base_metadata):
        chunks = strategy.chunk(glossary_content, base_metadata)
        assert all(c.metadata["chunk_type"] == "glossary_entry" for c in chunks)

    def test_glossary_term_in_metadata(self, strategy, glossary_content, base_metadata):
        chunks = strategy.chunk(glossary_content, base_metadata)
        terms = [c.metadata["glossary_term"] for c in chunks]
        assert "API" in terms
        assert "SDK" in terms
        assert "REST" in terms

    def test_term_formatted_bold_in_content(self, strategy, glossary_content, base_metadata):
        chunks = strategy.chunk(glossary_content, base_metadata)
        for chunk in chunks:
            term = chunk.metadata["glossary_term"]
            assert f"**{term}**" in chunk.content

    def test_definition_included_in_content(self, strategy, glossary_content, base_metadata):
        chunks = strategy.chunk(glossary_content, base_metadata)
        api_chunk = next(c for c in chunks if c.metadata["glossary_term"] == "API")
        assert "Application Programming Interface" in api_chunk.content

    def test_preserves_source_metadata(self, strategy, glossary_content, base_metadata):
        chunks = strategy.chunk(glossary_content, base_metadata)
        for chunk in chunks:
            assert chunk.metadata["source"] == "test.md"

    def test_term_category_defaults_to_general(self, strategy, glossary_content, base_metadata):
        chunks = strategy.chunk(glossary_content, base_metadata)
        assert all(c.metadata["term_category"] == "general" for c in chunks)

    def test_xref_count_tracks_links(self, strategy, base_metadata):
        text = "Term\n\nDefinition with [link1] and [link2] references."
        chunks = strategy.chunk(text, base_metadata)
        assert chunks[0].metadata["xref_count"] == 2

    def test_skips_section_headers(self, strategy, base_metadata):
        text = "# Header\n\n## Another Header\n\nActualTerm\n\nDefinition here."
        chunks = strategy.chunk(text, base_metadata)
        terms = [c.metadata["glossary_term"] for c in chunks]
        assert "# Header" not in terms
        assert "## Another Header" not in terms

    def test_returns_empty_for_no_valid_terms(self, strategy, base_metadata):
        text = "# Just Headers\n\n## And More Headers"
        chunks = strategy.chunk(text, base_metadata)
        assert chunks == []


class TestGlossaryChunkingStrategyTermDetection:

    @pytest.fixture
    def strategy(self):
        return GlossaryChunkingStrategy()

    def test_short_text_without_period_is_term(self, strategy):
        assert strategy._is_glossary_term("API") is True
        assert strategy._is_glossary_term("Software Development Kit") is True

    def test_text_ending_with_period_is_not_term(self, strategy):
        assert strategy._is_glossary_term("This is a sentence.") is False

    def test_text_ending_with_colon_is_not_term(self, strategy):
        assert strategy._is_glossary_term("Example:") is False

    def test_long_text_is_not_term(self, strategy):
        long_text = "A" * 81
        assert strategy._is_glossary_term(long_text) is False

    def test_exactly_80_chars_is_term(self, strategy):
        text = "A" * 80
        assert strategy._is_glossary_term(text) is True

    def test_whitespace_is_stripped(self, strategy):
        assert strategy._is_glossary_term("  Term  ") is True


class TestGlossaryChunkingStrategyMetadataEnrichment:

    @pytest.fixture
    def strategy(self):
        return GlossaryChunkingStrategy()

    def test_has_table_detected(self, strategy, base_metadata):
        # Include table separator pattern inline with definition text
        text = "TableTerm\n\nDefinition containing |---|--- table markup."
        chunks = strategy.chunk(text, base_metadata)
        assert len(chunks) == 1
        assert chunks[0].metadata["has_table"] is True

    def test_has_note_detected_for_tip(self, strategy, base_metadata):
        text = "TipTerm\n\n**Unser Tipp**\n\nSome tip content."
        chunks = strategy.chunk(text, base_metadata)
        assert chunks[0].metadata["has_note"] is True
        assert "tip" in chunks[0].metadata["note_types"]

    def test_has_note_detected_for_important(self, strategy, base_metadata):
        text = "ImportantTerm\n\n**Bitte beachten Sie**\n\nImportant content."
        chunks = strategy.chunk(text, base_metadata)
        assert chunks[0].metadata["has_note"] is True
        assert "important" in chunks[0].metadata["note_types"]

    def test_multiple_note_types(self, strategy, base_metadata):
        text = "MultiNoteTerm\n\n**Unser Tipp** is here.\n\n**Bitte beachten Sie** this is important."
        chunks = strategy.chunk(text, base_metadata)
        assert "tip" in chunks[0].metadata["note_types"]
        assert "important" in chunks[0].metadata["note_types"]
