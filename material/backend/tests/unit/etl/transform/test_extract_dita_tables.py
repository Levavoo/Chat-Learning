
import pytest

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.extract_dita_tables import extract_dita_tables


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
def transform() -> extract_dita_tables:
    return extract_dita_tables()


class TestExtractDitaTablesBasics:

    def test_original_item_is_passed_through_first(self, transform):
        xml = """<topic><title>T</title><body>
            <table><tgroup cols="2"><tbody>
                <row><entry>A</entry><entry>B</entry></row>
            </tbody></tgroup></table>
        </body></topic>"""
        result = transform.apply(_xml_item(xml, {"brochure_number": "B04"}))
        assert result[0].data_object.data == xml
        assert result[0].data_object.metadata == {"brochure_number": "B04"}

    def test_emits_one_item_per_table(self, transform):
        xml = """<topic><body>
            <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
            <table><tgroup cols="1"><tbody><row><entry>B</entry></row></tbody></tgroup></table>
        </body></topic>"""
        result = transform.apply(_xml_item(xml))
        assert len(result) == 3

    def test_emits_no_tables_when_none_present(self, transform):
        xml = "<topic><title>T</title><body><p>Plain</p></body></topic>"
        result = transform.apply(_xml_item(xml))
        assert len(result) == 1


class TestExtractDitaTablesMetadata:

    def test_table_inherits_source_metadata(self, transform):
        xml = """<topic><body>
            <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
        </body></topic>"""
        result = transform.apply(_xml_item(xml, {"brochure_number": "B04", "category": "Pflege"}))
        meta = result[1].data_object.metadata
        assert meta["brochure_number"] == "B04"
        assert meta["category"] == "Pflege"

    def test_table_metadata_marks_chunk_type_and_title(self, transform):
        xml = """<topic><body>
            <table><title>Pflegegrade nach SGB XI</title>
                <tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup>
            </table>
        </body></topic>"""
        result = transform.apply(_xml_item(xml))
        meta = result[1].data_object.metadata
        assert meta["chunk_type"] == "table"
        assert meta["table_title"] == "Pflegegrade nach SGB XI"

    def test_table_without_title_omits_table_title_metadata(self, transform):
        xml = """<topic><body>
            <table><title></title>
                <tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup>
            </table>
        </body></topic>"""
        result = transform.apply(_xml_item(xml))
        assert "table_title" not in result[1].data_object.metadata

    def test_section_title_tracked_from_ancestor(self, transform):
        xml = """<topic><body>
            <section><title>Pflegegrade</title>
                <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
            </section>
        </body></topic>"""
        result = transform.apply(_xml_item(xml))
        assert result[1].data_object.metadata["section_title"] == "Pflegegrade"

    def test_wintitle_tracked_as_subsection_for_sibling_table(self, transform):
        xml = """<topic><body>
            <section><title>Pflegegrade</title>
                <div>
                    <wintitle>Definition</wintitle>
                    <p>Setup paragraph.</p>
                    <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
                </div>
            </section>
        </body></topic>"""
        result = transform.apply(_xml_item(xml))
        meta = result[1].data_object.metadata
        assert meta["section_title"] == "Pflegegrade"
        assert meta["subsection_title"] == "Definition"

    def test_source_metadata_is_not_mutated_by_table_enrichment(self, transform):
        xml = """<topic><body>
            <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
        </body></topic>"""
        source_meta = {"brochure_number": "B04"}
        result = transform.apply(_xml_item(xml, source_meta))
        assert "chunk_type" not in source_meta
        assert "chunk_type" not in result[0].data_object.metadata


class TestExtractDitaTablesWrapperXml:

    def test_table_title_takes_precedence_over_section_context(self, transform):
        xml = """<topic><body>
            <section><title>Unrelated chapter</title>
                <p>Useful lead-in.</p>
                <table><title>Specific table title</title>
                    <tgroup cols="2"><tbody>
                        <row><entry>A</entry><entry>B</entry></row>
                    </tbody></tgroup>
                </table>
            </section>
        </body></topic>"""
        wrapper = transform.apply(_xml_item(xml))[1].data_object.data
        assert "<title>Specific table title</title>" in wrapper
        assert wrapper.count("Specific table title") == 1
        assert "Useful lead-in." in wrapper
        assert "<title>Unrelated chapter</title>" not in wrapper

    def test_note_heading_becomes_title_and_is_not_duplicated(self, transform):
        xml = """<topic><body>
            <section><title>Parent chapter</title>
                <p otherprops="note-ueberschrift">Flow title</p>
                <table><tgroup cols="1"><tbody>
                    <row><entry>Step one</entry></row>
                </tbody></tgroup></table>
            </section>
        </body></topic>"""
        wrapper = transform.apply(_xml_item(xml))[1].data_object.data
        assert wrapper.count("Flow title") == 1
        assert "<title>Flow title</title>" in wrapper
        assert 'otherprops="note-ueberschrift"' not in wrapper

    def test_duplicate_fallback_titles_are_disambiguated(self, transform):
        xml = """<topic><body>
            <section><title>Shared chapter</title>
                <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
                <table><tgroup cols="1"><tbody><row><entry>B</entry></row></tbody></tgroup></table>
            </section>
        </body></topic>"""
        result = transform.apply(_xml_item(xml))
        assert "<title>Shared chapter</title>" in result[1].data_object.data
        assert "<title>Shared chapter – Tabelle 2</title>" in result[2].data_object.data  # noqa: RUF001

    def test_wrapper_title_combines_section_and_subsection(self, transform):
        xml = """<topic><body>
            <section><title>Pflegegrade</title>
                <div>
                    <wintitle>Definition</wintitle>
                    <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
                </div>
            </section>
        </body></topic>"""
        wrapper = transform.apply(_xml_item(xml))[1].data_object.data
        assert "<title>Pflegegrade – Definition</title>" in wrapper  # noqa: RUF001

    def test_wrapper_includes_lead_in_paragraph(self, transform):
        xml = """<topic><body>
            <p>Folgende Pflegegrade gelten:</p>
            <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
        </body></topic>"""
        wrapper = transform.apply(_xml_item(xml))[1].data_object.data
        assert "Folgende Pflegegrade gelten:" in wrapper

    def test_wrapper_omits_lead_in_when_no_preceding_paragraph(self, transform):
        xml = """<topic><body>
            <section><title>Pflegegrade</title>
                <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
            </section>
        </body></topic>"""
        wrapper = transform.apply(_xml_item(xml))[1].data_object.data
        # body should contain only the table (no <p> child)
        assert "<p>" not in wrapper

    def test_wrapper_preserves_table_content(self, transform):
        xml = """<topic><body>
            <table id="t1"><title>My Title</title>
                <tgroup cols="2"><tbody>
                    <row><entry>head1</entry><entry>head2</entry></row>
                    <row><entry>cellA</entry><entry>cellB</entry></row>
                </tbody></tgroup>
            </table>
        </body></topic>"""
        wrapper = transform.apply(_xml_item(xml))[1].data_object.data
        assert "<title>My Title</title>" in wrapper
        assert "cellA" in wrapper
        assert "cellB" in wrapper

    def test_wrapper_falls_back_to_default_title_when_no_context(self, transform):
        xml = """<topic><body>
            <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
        </body></topic>"""
        wrapper = transform.apply(_xml_item(xml))[1].data_object.data
        assert "<title>Tabelle</title>" in wrapper


class TestExtractDitaTablesNaming:

    def test_table_items_get_unique_names(self, transform):
        xml = """<topic><body>
            <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
            <table><tgroup cols="1"><tbody><row><entry>B</entry></row></tbody></tgroup></table>
        </body></topic>"""
        result = transform.apply(_xml_item(xml, name="B04"))
        names = [it.data_object.name for it in result[1:]]
        assert names == ["B04_table_000", "B04_table_001"]


class TestExtractDitaTablesErrors:

    def test_malformed_xml_passes_through_without_tables(self, transform):
        result = transform.apply(_xml_item("<not valid xml"))
        assert len(result) == 1

    def test_bytes_data_is_decoded(self, transform):
        xml = """<topic><body>
            <table><tgroup cols="1"><tbody><row><entry>A</entry></row></tbody></tgroup></table>
        </body></topic>"""
        item = PipelineItem(
            name="doc",
            data_object=DataObject(name="doc", data=xml.encode("utf-8"), data_type=DataType.XML, metadata={}),
        )
        result = transform.apply(item)
        assert len(result) == 2
