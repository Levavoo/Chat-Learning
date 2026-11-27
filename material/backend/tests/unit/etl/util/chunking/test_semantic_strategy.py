
import pytest

from etl.util.chunking.semantic_strategy import SemanticChunkingStrategy


class TestSemanticChunkingStrategyChunk:

    @pytest.fixture
    def strategy(self):
        return SemanticChunkingStrategy()

    def test_returns_single_chunk(self, strategy, base_metadata):
        text = "Any content here, regardless of structure."
        chunks = strategy.chunk(text, base_metadata)
        assert len(chunks) == 1

    def test_chunk_contains_full_content(self, strategy, base_metadata):
        text = "Full document content\n\nWith multiple paragraphs."
        chunks = strategy.chunk(text, base_metadata)
        assert chunks[0].content == text

    def test_chunk_type_is_semantic_fallback(self, strategy, base_metadata):
        chunks = strategy.chunk("content", base_metadata)
        assert chunks[0].metadata["chunk_type"] == "semantic_fallback"

    def test_preserves_source_metadata(self, strategy, base_metadata):
        chunks = strategy.chunk("content", base_metadata)
        assert chunks[0].metadata["source"] == "test.md"
        assert chunks[0].metadata["doc_type"] == "test"

    def test_handles_empty_text(self, strategy, base_metadata):
        chunks = strategy.chunk("", base_metadata)
        assert len(chunks) == 1
        assert chunks[0].content == ""

    def test_handles_complex_markdown(self, strategy, markdown_with_h2_and_h3, base_metadata):
        chunks = strategy.chunk(markdown_with_h2_and_h3, base_metadata)
        assert len(chunks) == 1
        assert "## Main Section" in chunks[0].content
        assert "### Subsection A" in chunks[0].content


class TestSemanticChunkingStrategyMetadataEnrichment:

    @pytest.fixture
    def strategy(self):
        return SemanticChunkingStrategy()

    def test_has_table_true_when_table_present(self, strategy, markdown_with_table, base_metadata):
        chunks = strategy.chunk(markdown_with_table, base_metadata)
        assert chunks[0].metadata["has_table"] is True

    def test_has_table_false_when_no_table(self, strategy, base_metadata):
        chunks = strategy.chunk("Plain text without tables.", base_metadata)
        assert chunks[0].metadata["has_table"] is False

    def test_has_note_true_for_tip(self, strategy, markdown_with_tip_note, base_metadata):
        chunks = strategy.chunk(markdown_with_tip_note, base_metadata)
        assert chunks[0].metadata["has_note"] is True

    def test_has_note_true_for_important(self, strategy, markdown_with_important_note, base_metadata):
        chunks = strategy.chunk(markdown_with_important_note, base_metadata)
        assert chunks[0].metadata["has_note"] is True

    def test_has_note_false_when_no_notes(self, strategy, base_metadata):
        chunks = strategy.chunk("Plain text without notes.", base_metadata)
        assert chunks[0].metadata["has_note"] is False

    def test_note_types_includes_tip(self, strategy, markdown_with_tip_note, base_metadata):
        chunks = strategy.chunk(markdown_with_tip_note, base_metadata)
        assert "tip" in chunks[0].metadata["note_types"]

    def test_note_types_includes_important(self, strategy, markdown_with_important_note, base_metadata):
        chunks = strategy.chunk(markdown_with_important_note, base_metadata)
        assert "important" in chunks[0].metadata["note_types"]

    def test_multiple_note_types(self, strategy, base_metadata):
        text = "**Unser Tipp**\n\nTip.\n\n**Bitte beachten Sie**\n\nImportant."
        chunks = strategy.chunk(text, base_metadata)
        assert "tip" in chunks[0].metadata["note_types"]
        assert "important" in chunks[0].metadata["note_types"]

    def test_no_note_types_when_no_notes(self, strategy, base_metadata):
        chunks = strategy.chunk("Plain text.", base_metadata)
        assert "note_types" not in chunks[0].metadata


class TestSemanticChunkingStrategyAsFallback:

    @pytest.fixture
    def strategy(self):
        return SemanticChunkingStrategy()

    def test_handles_any_content_type(self, strategy, base_metadata):
        contents = [
            "",
            "Single line",
            "Line 1\nLine 2\nLine 3",
            "# H1\n## H2\n### H3",
            "| table |\n|-------|\n| data |",
            "```code\nblock\n```",
            "Mixed **bold** and *italic* and [links](url)",
        ]
        for content in contents:
            chunks = strategy.chunk(content, base_metadata)
            assert len(chunks) == 1
            assert chunks[0].content == content
