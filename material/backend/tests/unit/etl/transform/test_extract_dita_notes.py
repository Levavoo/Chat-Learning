
import pytest

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.extract_dita_notes import extract_dita_notes


def _xml_item(xml: str, metadata: dict | None = None, name: str = "doc") -> PipelineItem:
    return PipelineItem(
        name=name,
        data_object=DataObject(
            name=name,
            data=xml,
            data_type=DataType.XML,
            metadata=metadata or {},
        ),
    )


@pytest.fixture
def transform() -> extract_dita_notes:
    return extract_dita_notes()


class TestExtractDitaNotesBasics:

    def test_original_item_is_passed_through_first(self, transform):
        xml = """<topic><title>T</title><body>
            <note type="other" othertype="wichtig"><p>X</p></note>
        </body></topic>"""
        result = transform.apply(_xml_item(xml, {"brochure_number": "B34"}))
        assert result[0].data_object.data == xml
        assert result[0].data_object.metadata == {"brochure_number": "B34"}

    def test_emits_one_item_per_indexable_note(self, transform):
        xml = """<topic><title>T</title><body>
            <note type="other" othertype="wichtig"><p>A</p></note>
            <note type="other" othertype="wichtig"><p>B</p></note>
        </body></topic>"""
        result = transform.apply(_xml_item(xml))
        assert len(result) == 3

    def test_emits_no_notes_when_none_present(self, transform):
        xml = "<topic><title>T</title><body><p>Plain</p></body></topic>"
        result = transform.apply(_xml_item(xml))
        assert len(result) == 1

    def test_newsletter_notes_are_skipped(self, transform):
        xml = """<topic><title>T</title><body>
            <note type="other" othertype="wichtig"><p>A</p></note>
            <note type="other" othertype="newsletter"><p>Subscribe!</p></note>
        </body></topic>"""
        result = transform.apply(_xml_item(xml))
        assert len(result) == 2
        assert result[1].data_object.metadata["note_type"] == "wichtig"


class TestExtractDitaNotesMetadata:

    def test_note_inherits_source_metadata(self, transform):
        xml = """<topic><body><note type="other" othertype="wichtig"><p>X</p></note></body></topic>"""
        result = transform.apply(_xml_item(xml, {"brochure_number": "B34", "category": "Selbständige"}))
        meta = result[1].data_object.metadata
        assert meta["brochure_number"] == "B34"
        assert meta["category"] == "Selbständige"

    def test_note_metadata_marks_chunk_type_and_note_type(self, transform):
        xml = """<topic><body><note type="other" othertype="wichtig"><p>X</p></note></body></topic>"""
        result = transform.apply(_xml_item(xml))
        meta = result[1].data_object.metadata
        assert meta["chunk_type"] == "note"
        assert meta["note_type"] == "wichtig"

    def test_section_title_tracked_from_ancestor(self, transform):
        xml = """<topic><title>Doc</title><body>
            <section><title>Beitragsberechnung</title>
                <note type="other" othertype="wichtig"><p>X</p></note>
            </section>
        </body></topic>"""
        result = transform.apply(_xml_item(xml))
        assert result[1].data_object.metadata["section_title"] == "Beitragsberechnung"

    def test_wintitle_tracked_as_subsection_for_sibling_note(self, transform):
        xml = """<topic><body>
            <section><title>Beitragsberechnung</title>
                <div>
                    <wintitle>Sozialklausel</wintitle>
                    <p>Setup paragraph.</p>
                    <note type="other" othertype="wichtig"><p>X</p></note>
                </div>
            </section>
        </body></topic>"""
        result = transform.apply(_xml_item(xml))
        meta = result[1].data_object.metadata
        assert meta["section_title"] == "Beitragsberechnung"
        assert meta["subsection_title"] == "Sozialklausel"

    def test_subsection_omitted_when_no_wintitle(self, transform):
        xml = """<topic><body>
            <section><title>Sec</title>
                <note type="other" othertype="wichtig"><p>X</p></note>
            </section>
        </body></topic>"""
        result = transform.apply(_xml_item(xml))
        assert "subsection_title" not in result[1].data_object.metadata

    def test_source_metadata_is_not_mutated_by_note_enrichment(self, transform):
        xml = """<topic><body><note type="other" othertype="wichtig"><p>X</p></note></body></topic>"""
        source_meta = {"brochure_number": "B34"}
        result = transform.apply(_xml_item(xml, source_meta))
        assert "chunk_type" not in source_meta
        assert "chunk_type" not in result[0].data_object.metadata


class TestExtractDitaNotesWrapperXml:

    def test_wrapper_title_combines_section_and_subsection(self, transform):
        xml = """<topic><body>
            <section><title>Beitragsberechnung</title>
                <div>
                    <wintitle>Sozialklausel</wintitle>
                    <note type="other" othertype="wichtig"><p>X</p></note>
                </div>
            </section>
        </body></topic>"""
        wrapper = transform.apply(_xml_item(xml))[1].data_object.data
        assert "<title>Beitragsberechnung – Sozialklausel</title>" in wrapper  # noqa: RUF001

    def test_wrapper_preserves_note_content(self, transform):
        xml = """<topic><body>
            <note type="other" othertype="wichtig"><p>specific note content</p></note>
        </body></topic>"""
        wrapper = transform.apply(_xml_item(xml))[1].data_object.data
        assert "specific note content" in wrapper
        assert 'othertype="wichtig"' in wrapper

    def test_wrapper_falls_back_to_default_title_when_no_context(self, transform):
        xml = """<topic><body><note type="other" othertype="wichtig"><p>X</p></note></body></topic>"""
        wrapper = transform.apply(_xml_item(xml))[1].data_object.data
        assert "<title>Hinweis</title>" in wrapper


class TestExtractDitaNotesNaming:

    def test_note_items_get_unique_names(self, transform):
        xml = """<topic><body>
            <note type="other" othertype="wichtig"><p>A</p></note>
            <note type="other" othertype="wichtig"><p>B</p></note>
            <note type="other" othertype="wichtig"><p>C</p></note>
        </body></topic>"""
        result = transform.apply(_xml_item(xml, name="B34"))
        names = [it.data_object.name for it in result[1:]]
        assert names == ["B34_note_000", "B34_note_001", "B34_note_002"]


class TestExtractDitaNotesErrors:

    def test_malformed_xml_passes_through_without_notes(self, transform):
        result = transform.apply(_xml_item("<not valid xml"))
        assert len(result) == 1

    def test_bytes_data_is_decoded(self, transform):
        xml = """<topic><body><note type="other" othertype="wichtig"><p>X</p></note></body></topic>"""
        item = PipelineItem(
            name="doc",
            data_object=DataObject(name="doc", data=xml.encode("utf-8"), data_type=DataType.XML, metadata={}),
        )
        result = transform.apply(item)
        assert len(result) == 2
