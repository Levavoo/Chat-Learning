
import pytest

from etl.util.chunking.hierarchical_strategy import HierarchicalChunkingStrategy


class TestHierarchicalChunkingStrategyChunk:

    @pytest.fixture
    def strategy(self):
        return HierarchicalChunkingStrategy()

    def test_chunks_by_h2(self, strategy, markdown_with_h2_and_h3, base_metadata):
        chunks = strategy.chunk(markdown_with_h2_and_h3, base_metadata)
        section_chunks = [c for c in chunks if c.metadata["chunk_type"] == "hierarchical_section"]
        assert len(section_chunks) == 2

    def test_section_titles_in_metadata(self, strategy, markdown_with_h2_and_h3, base_metadata):
        chunks = strategy.chunk(markdown_with_h2_and_h3, base_metadata)
        titles = [c.metadata["section_title"] for c in chunks]
        assert "Main Section" in titles
        assert "Another Section" in titles

    def test_h3_content_kept_inside_h2_chunk(self, strategy, markdown_with_h2_and_h3, base_metadata):
        chunks = strategy.chunk(markdown_with_h2_and_h3, base_metadata)
        main = next(c for c in chunks if c.metadata["section_title"] == "Main Section")
        assert "### Subsection A" in main.content
        assert "### Subsection B" in main.content

    def test_preserves_source_metadata(self, strategy, markdown_with_h2_and_h3, base_metadata):
        chunks = strategy.chunk(markdown_with_h2_and_h3, base_metadata)
        for chunk in chunks:
            assert chunk.metadata["source"] == "test.md"

    def test_returns_empty_for_no_h2_sections(self, strategy, base_metadata):
        text = "# H1 Only\n\nSome content without H2 sections."
        chunks = strategy.chunk(text, base_metadata)
        assert chunks == []


class TestHierarchicalChunkingStrategyOversizedSplit:

    def test_large_section_is_split_with_overlap(self, base_metadata):
        strategy = HierarchicalChunkingStrategy(section_split_threshold=500, section_overlap=50)
        text = "## Big Section\n\n" + ("Lorem ipsum dolor sit amet. " * 80)
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) > 1
        assert all(c.metadata["chunk_type"] == "hierarchical_section_split" for c in chunks)
        assert all(c.metadata["section_title"] == "Big Section" for c in chunks)

    def test_small_section_stays_single_chunk(self, base_metadata):
        strategy = HierarchicalChunkingStrategy(section_split_threshold=2500)
        text = "## Small Section\n\nShort content here."
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) == 1
        assert chunks[0].metadata["chunk_type"] == "hierarchical_section"

    def test_default_threshold_is_2500(self):
        strategy = HierarchicalChunkingStrategy()
        assert strategy.section_split_threshold == 2500

    def test_split_chunks_never_start_with_whitespace(self, base_metadata):
        r"""Regression: Bedrock drops chunks beginning with "\n(" as "format not supported".

        split_text_with_overlap can begin a sub-chunk on a newline boundary (e.g. a
        paragraph break right before a parenthetical note), producing a chunk that
        starts with "\n(". Bedrock's content-type sniffer (Apache Tika) misdetects
        such a file as an unsupported binary format and silently skips it at
        ingestion. Emitted chunks must therefore never carry leading/trailing
        whitespace. The params below are tuned to reproduce the newline-boundary
        split (verified: the raw splitter emits a leading-whitespace sub here).
        """
        note = "(Zu den verschiedenen Rehabilitationsformen lesen Sie bitte ab Seite 5.)"
        para1 = "Dies ist ein vorbereitender Absatz mit genuegend Text. " * 6
        para2 = "Im Sozialbericht empfiehlt die Beratungsstelle die geeignete Form. " * 6
        section = para1.strip() + "\n\n" + note + "Weiterer Text nach dem Hinweis. " * 6 + "\n\n" + para2.strip()
        text = "## Titel\n\n" + section

        strategy = HierarchicalChunkingStrategy(section_split_threshold=150, section_overlap=20)
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) > 1  # the oversized-split path must have run
        assert all(c.metadata["chunk_type"] == "hierarchical_section_split" for c in chunks)
        for c in chunks:
            assert c.content == c.content.strip()
            assert not c.content.startswith("\n")


class TestHierarchicalChunkingStrategyMetadataEnrichment:

    @pytest.fixture
    def strategy(self):
        return HierarchicalChunkingStrategy()

    def test_has_table_detected(self, strategy, base_metadata):
        text = """## Section With Table

| A | B |
|---|---|
| 1 | 2 |
"""
        chunks = strategy.chunk(text, base_metadata)
        assert chunks[0].metadata["has_table"] is True

    def test_has_note_detected(self, strategy, base_metadata):
        text = """## Section With Tip

**Unser Tipp**

A helpful tip.
"""
        chunks = strategy.chunk(text, base_metadata)
        assert chunks[0].metadata["has_note"] is True

    def test_note_types_populated(self, strategy, base_metadata):
        text = """## Section With Notes

**Unser Tipp**

Tip content.

**Bitte beachten Sie**

Important content.
"""
        chunks = strategy.chunk(text, base_metadata)
        assert "tip" in chunks[0].metadata["note_types"]
        assert "important" in chunks[0].metadata["note_types"]


class TestHierarchicalChunkingStrategyExtractSections:

    @pytest.fixture
    def strategy(self):
        return HierarchicalChunkingStrategy()

    def test_extracts_h2_sections(self, strategy):
        text = "## One\n\nContent\n\n## Two\n\nMore"
        sections = strategy._extract_sections(text, level=2)
        assert len(sections) == 2

    def test_section_metadata_contains_title(self, strategy):
        text = "## My Title\n\nContent here"
        sections = strategy._extract_sections(text, level=2)
        assert sections[0].metadata["title"] == "My Title"


class TestHierarchicalChunkingStrategyStartBoundaries:

    def test_split_sub_chunks_never_begin_mid_token(self, base_metadata):
        words = ["Rentenversicherungsträger", "berufsunfähig", "Informationen"]
        vocab = set(words) | {f"Wort{i:03d}" for i in range(120)}
        body = " ".join(f"Wort{i:03d} {words[i % 3]}" for i in range(120))
        text = "## Abschnitt\n\n" + body
        assert "." not in body

        strategy = HierarchicalChunkingStrategy(section_split_threshold=200, section_overlap=60)
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) > 1
        assert all(c.metadata["chunk_type"] == "hierarchical_section_split" for c in chunks)
        for chunk in chunks[1:]:
            first_token = chunk.content.split(maxsplit=1)[0]
            assert first_token in vocab, f"sub-chunk begins mid-token: {chunk.content[:40]!r}"
