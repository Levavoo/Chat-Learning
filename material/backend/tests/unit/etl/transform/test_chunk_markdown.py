from unittest.mock import patch

import pytest

from etl.models import DataObject, DataType, PipelineItem, SourceObject
from etl.transform.chunk_markdown import chunk_markdown
from etl.util.chunking.base import Chunk
from etl.util.chunking.flat_section_strategy import FlatSectionChunkingStrategy
from etl.util.merkblatt_markdown import render_sections_to_markdown


@pytest.fixture
def transform():
    return chunk_markdown()


@pytest.fixture
def sample_hierarchical_markdown():
    return """# Document Title

## Section 1

### Subsection 1.1
Content for subsection 1.1.

### Subsection 1.2
Content for subsection 1.2.

## Section 2

### Subsection 2.1
Content for subsection 2.1.
"""


@pytest.fixture
def sample_flat_markdown():
    return """# Document Title

## Section 1
Content for section 1.

## Section 2
Content for section 2.
"""


@pytest.fixture
def sample_glossary_markdown():
    return """# Glossary

Term One

Definition of term one.

Term Two

Definition of term two.
"""


@pytest.fixture
def sample_pipeline_item_bytes():
    data_object = DataObject(
        name="sample-document",
        data=b"# Sample Document\n\nThis is a sample markdown document.",
        data_type=DataType.MARKDOWN,
        metadata={"name": "sample-document"},
    )
    return PipelineItem(name="sample-document", data_object=data_object)


@pytest.fixture
def sample_pipeline_item_str():
    data_object = DataObject(
        name="sample-document",
        data="# Sample Document\n\nThis is a sample markdown document.",
        data_type=DataType.MARKDOWN,
        metadata={"name": "sample-document"},
    )
    return PipelineItem(name="sample-document", data_object=data_object)


class TestChunkMarkdownApply:
    def test_apply_returns_list_of_pipeline_items(
        self, transform: chunk_markdown, sample_pipeline_item_str: PipelineItem
    ):
        result = transform.apply(sample_pipeline_item_str)

        assert isinstance(result, list)
        assert all(isinstance(item, PipelineItem) for item in result)
        assert len(result) > 0

    def test_apply_handles_bytes_input(self, transform: chunk_markdown, sample_pipeline_item_bytes: PipelineItem):
        result = transform.apply(sample_pipeline_item_bytes)

        assert isinstance(result, list)
        assert all(isinstance(item, PipelineItem) for item in result)
        assert len(result) > 0
        assert all(isinstance(item.data_object.data, str) for item in result)

    def test_apply_handles_string_input(self, transform: chunk_markdown, sample_pipeline_item_str: PipelineItem):
        result = transform.apply(sample_pipeline_item_str)

        assert isinstance(result, list)
        assert all(isinstance(item, PipelineItem) for item in result)
        assert len(result) > 0
        assert all(isinstance(item.data_object.data, str) for item in result)

    def test_chunk_names_follow_pattern(self, transform: chunk_markdown, sample_hierarchical_markdown: str):
        data = DataObject(
            name="document.md",
            data=sample_hierarchical_markdown,
            data_type=DataType.MARKDOWN,
            metadata={},
        )
        item = PipelineItem(name="document.md", data_object=data)

        result = transform.apply(item)
        for i, chunk_item in enumerate(result):
            expected_name = f"document/document_{i:04d}"
            assert chunk_item.name == expected_name

    def test_chunks_preserve_original_metadata(self, transform: chunk_markdown, sample_pipeline_item_str: PipelineItem):
        result = transform.apply(sample_pipeline_item_str)

        for chunk_item in result:
            for key, value in sample_pipeline_item_str.data_object.metadata.items():
                assert chunk_item.data_object.metadata.get(key) == value

    def test_apply_strips_whitespace_and_skips_empty_chunks(
        self, transform: chunk_markdown, sample_pipeline_item_str: PipelineItem
    ):
        r"""Regression: never write a chunk that starts with "\n(".

        Bedrock's ingestion content-type sniffer (Apache Tika) misdetects a file
        beginning with a newline followed by "(" as an unsupported binary format and
        silently skips it ("file format was not supported"). The write step is the
        single funnel for every strategy, so it must strip each chunk and drop
        empties while keeping the chunk indices contiguous.
        """
        crafted = [
            Chunk(content="\n(Ein Hinweis zur Seite.)Echter Inhalt folgt hier.", metadata={}),
            Chunk(content="   \n  \t ", metadata={}),
            Chunk(content="## Abschnitt\n\nInhalt.\n", metadata={}),
        ]
        with patch.object(transform, "_select_chunking_strategy") as mock_select:
            mock_select.return_value.chunk.return_value = crafted
            result = transform.apply(sample_pipeline_item_str)

        assert len(result) == 2
        for item in result:
            data = item.data_object.data
            assert isinstance(data, str)
            assert data == data.strip()
            assert not data.startswith("\n")
        assert result[0].data_object.name.endswith("_0000")
        assert result[1].data_object.name.endswith("_0001")


class TestChunkingStrategySelection:
    @pytest.mark.parametrize(
        ("brochure_number", "expected_strategy"),
        [
            ("B28", "GlossaryChunkingStrategy"),
            ("B37", "GlossaryChunkingStrategy"),
            ("B38", "FlatSectionChunkingStrategy"),
        ],
        ids=["glossary-B28", "glossary-B37", "flat-B38"],
    )
    def test_selects_strategy_by_brochure_number(
        self, transform: chunk_markdown, brochure_number: str, expected_strategy: str
    ):
        metadata = {"brochure_number": brochure_number}
        strategy = transform._select_chunking_strategy("", metadata)
        assert strategy.__class__.__name__ == expected_strategy

    @pytest.mark.parametrize(
        ("markdown", "expected_strategy"),
        [
            pytest.param(
                "# Doc\n\n## S1\n\n### A\ntext\n\n### B\ntext\n\n### C\ntext\n",
                "HierarchicalChunkingStrategy",
                id="hierarchical-with-h3-headers",
            ),
            pytest.param(
                "# Doc\n\n## S1\ntext\n\n## S2\ntext\n",
                "FlatSectionChunkingStrategy",
                id="flat-fallback",
            ),
        ],
    )
    def test_selects_strategy_by_document_structure(
        self, transform: chunk_markdown, markdown: str, expected_strategy: str
    ):
        strategy = transform._select_chunking_strategy(markdown, {})
        assert strategy.__class__.__name__ == expected_strategy


class TestHeaderlessFallbackScopedToPdf:
    """The headerless paragraph fallback must be reachable for PDFs only.

    The chunker is format-agnostic and wired into both PDF and DITA/XML chains,
    so the fallback is gated on source_object.data_type (set from the file
    extension at ingest and never rewritten by a transform).
    """

    @staticmethod
    def _large_headerless_item(data_type: DataType) -> PipelineItem:
        """Build an item whose content has no H2/H3 and exceeds the fallback target."""
        paragraphs = [f"Absatz {i}: " + "lorem ipsum dolor sit amet " * 10 for i in range(60)]
        text = "\n\n".join(paragraphs)
        assert len(text) > FlatSectionChunkingStrategy.FALLBACK_CHUNK_TARGET
        data_object = DataObject(
            name="headerless",
            data=text,
            data_type=DataType.MARKDOWN,
            metadata={"name": "headerless"},
        )
        source_object = SourceObject(name="headerless", data_type=data_type, source="headerless", metadata={})
        return PipelineItem(name="headerless", source_object=source_object, data_object=data_object)

    def test_pdf_sourced_headerless_doc_is_paragraph_chunked(self, transform: chunk_markdown):
        result = transform.apply(self._large_headerless_item(DataType.PDF))
        assert len(result) > 1
        assert all(item.data_object.metadata["chunk_type"] == "flat_paragraph_fallback" for item in result)

    def test_xml_sourced_headerless_doc_is_not_paragraph_chunked(self, transform: chunk_markdown):
        result = transform.apply(self._large_headerless_item(DataType.XML))
        assert len(result) == 1
        assert result[0].data_object.metadata.get("chunk_type") != "flat_paragraph_fallback"

    def test_select_strategy_forwards_fallback_flag(self, transform: chunk_markdown):
        enabled = transform._select_chunking_strategy("plain text", {}, enable_headerless_fallback=True)
        disabled = transform._select_chunking_strategy("plain text", {}, enable_headerless_fallback=False)
        assert isinstance(enabled, FlatSectionChunkingStrategy)
        assert isinstance(disabled, FlatSectionChunkingStrategy)
        assert enabled.enable_headerless_fallback is True
        assert disabled.enable_headerless_fallback is False


class TestHierarchicalDetection:
    def test_detects_hierarchical_with_many_h3_headers(self, transform: chunk_markdown):
        markdown = """# Title
## Section
### Subsection 1
### Subsection 2
### Subsection 3
"""
        assert transform._has_hierarchical_sections(markdown) is True

    def test_returns_false_for_few_h3_headers(self, transform: chunk_markdown):
        markdown = """# Title
## Section
### Subsection 1
### Subsection 2
"""
        assert transform._has_hierarchical_sections(markdown) is False

    def test_respects_min_divs_threshold_parameter(self, transform: chunk_markdown):
        transform.min_divs_for_hierarchical = 2
        markdown = """# Title
## Section
### Subsection 1
### Subsection 2
"""
        assert transform._has_hierarchical_sections(markdown) is True


class TestChunkMetadata:
    def test_hierarchical_chunks_have_required_metadata_fields(
        self, transform: chunk_markdown, sample_hierarchical_markdown: str
    ):
        data = DataObject(
            name="doc.md",
            data=sample_hierarchical_markdown,
            data_type=DataType.MARKDOWN,
            metadata={},
        )
        item = PipelineItem(name="doc.md", data_object=data)
        result = transform.apply(item)

        for chunk in result:
            metadata = chunk.data_object.metadata
            assert "section_title" in metadata, "Missing section_title"
            assert "chunk_type" in metadata, "Missing chunk_type"


class TestContextualGroundingIntegration:
    @pytest.fixture(autouse=True)
    def enable_contextual_grounding(self, monkeypatch):
        monkeypatch.setenv("CONTEXTUAL_GROUNDING_ENABLED", "true")
        monkeypatch.setattr(
            "etl.util.chunking.contextual_grounding.generate_document_summary",
            lambda doc: None,
        )

    def test_chunks_contain_contextual_header_when_metadata_present(
        self, transform: chunk_markdown, sample_hierarchical_markdown: str
    ):
        data = DataObject(
            name="doc.md",
            data=sample_hierarchical_markdown,
            data_type=DataType.MARKDOWN,
            metadata={"name": "Die Rentenversicherung", "category": "Rente"},
        )
        item = PipelineItem(name="doc.md", data_object=data)
        result = transform.apply(item)

        for chunk_item in result:
            content = str(chunk_item.data_object.data)
            assert "**Quelle:** Die Rentenversicherung" in content
            assert "---" in content

    def test_chunks_contain_section_context(self, transform: chunk_markdown, sample_hierarchical_markdown: str):
        data = DataObject(
            name="doc.md",
            data=sample_hierarchical_markdown,
            data_type=DataType.MARKDOWN,
            metadata={"name": "Test Brochure"},
        )
        item = PipelineItem(name="doc.md", data_object=data)
        result = transform.apply(item)

        has_section_context = any("**Abschnitt:**" in str(item.data_object.data) for item in result)
        assert has_section_context

    def test_no_header_when_metadata_empty(self, transform: chunk_markdown, sample_hierarchical_markdown: str):
        data = DataObject(
            name="doc.md",
            data=sample_hierarchical_markdown,
            data_type=DataType.MARKDOWN,
            metadata={},
        )
        item = PipelineItem(name="doc.md", data_object=data)
        result = transform.apply(item)

        for chunk_item in result:
            assert not str(chunk_item.data_object.data).startswith("**Quelle:**")

    @patch("etl.util.chunking.contextual_grounding.generate_document_summary")
    def test_passes_full_document_to_contextual_grounding(
        self, mock_generate, transform: chunk_markdown, sample_hierarchical_markdown: str
    ):
        mock_generate.return_value = None
        data = DataObject(
            name="doc.md",
            data=sample_hierarchical_markdown,
            data_type=DataType.MARKDOWN,
            metadata={"name": "Test"},
        )
        item = PipelineItem(name="doc.md", data_object=data)
        transform.apply(item)

        mock_generate.assert_called_once_with(sample_hierarchical_markdown)


class TestEnrichMetadataFromFilename:
    def test_skips_when_brochure_number_already_set(self, transform: chunk_markdown):
        metadata = {"brochure_number": "B01", "name": "Existing"}
        transform._enrich_metadata_from_filename("IN/V0090", metadata)
        assert metadata["brochure_number"] == "B01"
        assert metadata["name"] == "Existing"

    def test_extracts_brochure_number_from_filename(self, transform: chunk_markdown):
        metadata: dict = {}
        transform._enrich_metadata_from_filename("IN/V0090", metadata)
        assert metadata["brochure_number"] == "V0090"

    def test_strips_file_extension(self, transform: chunk_markdown):
        metadata: dict = {}
        transform._enrich_metadata_from_filename("V0090.pdf", metadata)
        assert metadata["brochure_number"] == "V0090"

    def test_resolves_name_from_mapping(self, transform: chunk_markdown):
        metadata: dict = {}
        transform._enrich_metadata_from_filename("V0090", metadata)
        assert metadata["name"] == "Merkblatt zum Versicherungsschutz"

    def test_resolves_url_from_mapping(self, transform: chunk_markdown):
        metadata: dict = {}
        transform._enrich_metadata_from_filename("V0090", metadata)
        assert "deutsche-rentenversicherung.de" in metadata["brochure_url"]

    def test_resolves_short_url_from_id(self, transform: chunk_markdown):
        metadata: dict = {}
        transform._enrich_metadata_from_filename("V0090", metadata)
        assert metadata["brochure_url_short"] == "https://www.deutsche-rentenversicherung.de/V0090"

    def test_no_short_url_when_no_mapping(self, transform: chunk_markdown):
        metadata: dict = {}
        transform._enrich_metadata_from_filename("X9999", metadata)
        assert "brochure_url_short" not in metadata

    def test_warns_on_missing_mapping_for_brochure_id(self, transform: chunk_markdown, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            metadata: dict = {}
            transform._enrich_metadata_from_filename("X9999", metadata)
        assert any("No display name mapping" in r.message for r in caplog.records)
        assert any("No URL mapping" in r.message for r in caplog.records)

    def test_no_warning_for_non_brochure_filenames(self, transform: chunk_markdown, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            metadata: dict = {}
            transform._enrich_metadata_from_filename("some-random-file", metadata)
        assert not any("No display name" in r.message for r in caplog.records)

    def test_merkblatt_prefix_sets_category(self, transform: chunk_markdown):
        for stem in ("V0017", "G0103", "R0815"):
            metadata: dict = {}
            transform._enrich_metadata_from_filename(stem, metadata)
            assert metadata["category"] == "Merkblatt", f"Expected Merkblatt for {stem}"

    def test_broschure_prefix_does_not_set_merkblatt_category(self, transform: chunk_markdown):
        for stem in ("B28", "F06", "FB01"):
            metadata: dict = {}
            transform._enrich_metadata_from_filename(stem, metadata)
            assert metadata.get("category") != "Merkblatt", f"Should not be Merkblatt for {stem}"

    def test_existing_category_not_overwritten(self, transform: chunk_markdown):
        metadata: dict = {"category": "Rente"}
        transform._enrich_metadata_from_filename("V0017", metadata)
        assert metadata["category"] == "Rente"


class TestMerkblattStructuredMarkdown:
    """#501: a rendered Merkblatt .md chunks along its sections, not fixed-size blocks.

    Ingested as DataType.MARKDOWN (headerless fallback OFF), the structured
    Markdown produced by ``render_sections_to_markdown`` must yield
    ``flat_section``/``flat_section_split`` chunks that all carry a
    ``section_title`` — and never a ``flat_paragraph_fallback`` chunk.
    """

    @staticmethod
    def _merkblatt_item() -> PipelineItem:
        doc = {
            "doc_id": "V0090",
            "title": "Hinweis zur Aufrechterhaltung des Versicherungsschutzes",
            "sections": [
                {"title": "", "content": "V0090\nDieses Hinweisblatt informiert Sie über den Schutz."},
                {"title": "Ist mein Versicherungsschutz gefährdet?", "content": "Der Anspruch bleibt bestehen."},
                {"title": "Was muss ich tun?", "content": "Sie müssen fristgerecht Beiträge zahlen. " * 120},
            ],
        }
        md = render_sections_to_markdown(doc)
        data_object = DataObject(name="V0090.md", data=md, data_type=DataType.MARKDOWN, metadata={})
        source_object = SourceObject(name="V0090.md", data_type=DataType.MARKDOWN, source="s3", metadata={})
        return PipelineItem(name="V0090.md", source_object=source_object, data_object=data_object)

    def test_chunks_are_section_aligned_with_titles(self, transform: chunk_markdown):
        result = transform.apply(self._merkblatt_item())

        assert len(result) >= 3, "intro + 2 sections (one split) → at least 3 chunks"
        chunk_types = {item.data_object.metadata.get("chunk_type") for item in result}
        assert chunk_types <= {"flat_section", "flat_section_split"}, chunk_types
        assert "flat_paragraph_fallback" not in chunk_types
        for item in result:
            md = item.data_object.metadata
            assert md.get("section_title"), "every Merkblatt chunk must carry a section_title"
            assert md.get("brochure_number") == "V0090"
            assert md.get("category") == "Merkblatt"

    def test_oversized_section_splits_and_keeps_parent_title(self, transform: chunk_markdown):
        result = transform.apply(self._merkblatt_item())

        split = [i for i in result if i.data_object.metadata.get("chunk_type") == "flat_section_split"]
        assert split, "the >2500-char section must produce flat_section_split chunks"
        assert all(i.data_object.metadata.get("section_title") == "Was muss ich tun?" for i in split)

    def test_intro_preamble_is_preserved_as_titled_chunk(self, transform: chunk_markdown):
        result = transform.apply(self._merkblatt_item())

        intro = [i for i in result if "Dieses Hinweisblatt informiert" in str(i.data_object.data)]
        assert intro, "the empty-title intro must survive as its own titled chunk"
        assert intro[0].data_object.metadata.get("section_title") == (
            "Hinweis zur Aufrechterhaltung des Versicherungsschutzes"
        )
