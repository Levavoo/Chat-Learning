
import os
from unittest.mock import patch

from etl.util.chunking.base import Chunk
from etl.util.chunking.contextual_grounding import (
    CONTEXT_SEPARATOR,
    apply_contextual_grounding,
    build_context_header,
)


class TestBuildContextHeader:

    def test_full_metadata(self):
        metadata = {
            "name": "Die Rentenversicherung",
            "category": "Rente",
            "section_title": "Leistungen",
            "subsection_title": "Wartezeiten",
        }
        header = build_context_header(metadata)

        assert "**Quelle:** Die Rentenversicherung" in header
        assert "**Kategorie:** Rente" in header
        assert "**Abschnitt:** Leistungen → Wartezeiten" in header

    def test_name_only(self):
        header = build_context_header({"name": "Die Rentenversicherung"})
        assert header == "**Quelle:** Die Rentenversicherung"

    def test_section_without_subsection(self):
        header = build_context_header({"section_title": "Leistungen"})
        assert "**Abschnitt:** Leistungen" in header
        assert "→" not in header

    def test_category_only(self):
        header = build_context_header({"category": "Rente"})
        assert header == "**Kategorie:** Rente"

    def test_empty_metadata(self):
        assert build_context_header({}) == ""

    def test_ignores_unknown_fields(self):
        header = build_context_header({"brochure_number": "B01", "chunk_type": "hierarchical_div"})
        assert header == ""


@patch.dict(os.environ, {"CONTEXTUAL_GROUNDING_ENABLED": "true"})
class TestApplyContextualGrounding:

    def test_prepends_header_to_content(self):
        chunks = [
            Chunk(
                content="Some content here.",
                metadata={"name": "Test"},
            )
        ]
        result = apply_contextual_grounding(chunks)

        assert len(result) == 1
        assert result[0].content.startswith("**Quelle:** Test")
        assert CONTEXT_SEPARATOR in result[0].content
        assert result[0].content.endswith("Some content here.")

    def test_skips_chunks_without_metadata(self):
        chunks = [Chunk(content="Raw content.", metadata={})]
        result = apply_contextual_grounding(chunks)

        assert result[0].content == "Raw content."

    def test_processes_multiple_chunks(self):
        chunks = [
            Chunk(content="Content A.", metadata={"name": "Brochure A"}),
            Chunk(content="Content B.", metadata={"name": "Brochure B"}),
        ]
        result = apply_contextual_grounding(chunks)

        assert "Brochure A" in result[0].content
        assert "Brochure B" in result[1].content

    def test_preserves_metadata(self):
        metadata = {"name": "Test", "section_title": "Leistungen"}
        chunks = [Chunk(content="Content.", metadata=metadata)]
        result = apply_contextual_grounding(chunks)

        assert result[0].metadata == metadata

    def test_default_full_document_empty(self):
        chunks = [Chunk(content="Content.", metadata={"name": "Test"})]
        result = apply_contextual_grounding(chunks)

        assert "**Quelle:** Test" in result[0].content


@patch.dict(os.environ, {"CONTEXTUAL_GROUNDING_ENABLED": "true"})
class TestApplyContextualGroundingWithLLM:

    @patch("etl.util.chunking.contextual_grounding.generate_document_summary")
    def test_uses_llm_context_when_available(self, mock_generate):
        mock_generate.return_value = "LLM-generierter Kontext."
        chunks = [Chunk(content="Content.", metadata={"name": "Test"})]

        result = apply_contextual_grounding(chunks, full_document="Full doc text")

        assert result[0].content.startswith("<!-- LLM-generierter Kontext. -->")
        assert CONTEXT_SEPARATOR in result[0].content
        assert result[0].content.endswith("Content.")

    @patch("etl.util.chunking.contextual_grounding.generate_document_summary")
    def test_falls_back_to_static_when_llm_returns_none(self, mock_generate):
        mock_generate.return_value = None
        chunks = [Chunk(content="Content.", metadata={"name": "Test"})]

        result = apply_contextual_grounding(chunks, full_document="Full doc text")

        assert "**Quelle:** Test" in result[0].content

    @patch("etl.util.chunking.contextual_grounding.generate_document_summary")
    def test_skips_llm_when_no_full_document(self, mock_generate):
        chunks = [Chunk(content="Content.", metadata={"name": "Test"})]

        apply_contextual_grounding(chunks, full_document="")

        mock_generate.assert_not_called()

    @patch("etl.util.chunking.contextual_grounding.generate_document_summary")
    def test_llm_context_preserves_metadata(self, mock_generate):
        mock_generate.return_value = "LLM context."
        metadata = {"name": "Test", "category": "Rente"}
        chunks = [Chunk(content="Content.", metadata=metadata)]

        result = apply_contextual_grounding(chunks, full_document="doc")

        assert result[0].metadata == metadata
