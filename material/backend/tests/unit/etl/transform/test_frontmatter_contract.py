"""Regression: no searchable output body carries YAML frontmatter (#696).

Drives the real transform chains for every ETL output path (regular brochure,
extracted note, extracted table, FAQ) and asserts the produced ``.md`` body is
clean Markdown while the metadata that feeds the ``.metadata.json`` sidecar is
retained. This guards the one content/metadata contract: the bytes Bedrock
embeds and BM25 returns equal the stored body, and custom metadata lives only in
the sidecar.
"""

import re
from unittest.mock import patch

from etl.models import DataObject, DataType, PipelineItem, SourceObject
from etl.transform.chunk_markdown import chunk_markdown
from etl.transform.convert_to_html import dita_to_html
from etl.transform.convert_to_md import text_to_md
from etl.transform.extract_dita_notes import extract_dita_notes
from etl.transform.extract_dita_tables import extract_dita_tables
from etl.transform.filter_html import prepare_faq_html

# A leading YAML frontmatter block: `---\n … \n---`.
_FRONTMATTER_HEAD_RE = re.compile(r"^---\n.*?\n---", re.DOTALL)


def assert_no_frontmatter(body: object) -> None:
    assert isinstance(body, str)
    assert not body.startswith("---"), f"body starts with '---': {body[:120]!r}"
    assert _FRONTMATTER_HEAD_RE.match(body) is None, f"body opens with a frontmatter block: {body[:160]!r}"


def _xml_item(xml: str, metadata: dict, name: str = "B01") -> PipelineItem:
    return PipelineItem(
        name=name,
        source_object=SourceObject(name=name, data_type=DataType.XML, source="", metadata={}),
        data_object=DataObject(name=name, data=xml, data_type=DataType.XML, metadata=metadata),
    )


def _run_chain(item: PipelineItem, *transforms) -> list[PipelineItem]:
    items = [item]
    for transform in transforms:
        next_items: list[PipelineItem] = []
        for current in items:
            next_items.extend(transform.apply(current))
        items = next_items
    return items


_FAQ_URL = "https://www.deutsche-rentenversicherung.de/faq"
_FAQ_MAPPING = {"faq-a-und-b.md": _FAQ_URL}
_FAQ_HTML = (
    "<!DOCTYPE html><html>"
    '<head><meta name="dc.date" content="2024-01-01"></head>'
    '<body><div class="c-accordion">'
    '<h2 class="c-accordion__heading"><button aria-controls="content-0">'
    "Wie beantrage ich meine Rente?</button></h2>"
    '<div class="c-accordion__content" id="content-0"><p>Sie stellen einen Rentenantrag.</p></div>'
    '<h2 class="c-accordion__heading"><button aria-controls="contact">'
    "Ihre Frage war nicht dabei?</button></h2>"
    '<div class="c-accordion__content" id="contact"><p>Kontakt</p></div>'
    "</div></body></html>"
)


class TestRegularPathContract:

    def test_multi_h2_document_chunks_have_no_frontmatter(self):
        xml = (
            '<?xml version="1.0"?>'
            '<concept id="reg"><title>Rentenüberblick</title><conbody>'
            "<p>Einleitung zur Rente.</p>"
            '<section id="s1"><title>Altersrente</title><p>Text über Altersrente.</p></section>'
            '<section id="s2"><title>Erwerbsminderung</title><p>Text über Erwerbsminderung.</p></section>'
            "</conbody></concept>"
        )
        item = _xml_item(xml, {"brochure_number": "B01", "name": "Rentenüberblick"})
        chunks = _run_chain(item, dita_to_html(), text_to_md(), chunk_markdown())

        # Two H2 sections -> two chunks; the frontmatter-bearing preamble/H1 is discarded.
        assert len(chunks) == 2
        for chunk in chunks:
            assert_no_frontmatter(chunk.data_object.data)
            assert chunk.data_object.metadata["brochure_number"] == "B01"

    def test_headerless_single_chunk_document_has_no_frontmatter(self):
        xml = (
            '<?xml version="1.0"?>'
            '<concept id="hl"><title>Kontenklärung</title><conbody>'
            "<p>Nur ein Absatz ohne weitere Abschnitte.</p>"
            "<p>Noch ein Absatz.</p>"
            "</conbody></concept>"
        )
        item = _xml_item(xml, {"brochure_number": "B02", "name": "Kontenklärung"})
        chunks = _run_chain(item, dita_to_html(), text_to_md(), chunk_markdown())

        assert len(chunks) == 1
        assert_no_frontmatter(chunks[0].data_object.data)
        assert chunks[0].data_object.metadata["brochure_number"] == "B02"


class TestNotePathContract:

    def test_trailing_space_in_author_heading_does_not_duplicate_colon(self):
        xml = (
            "<topic><title>Vorsicht, Grenze!</title><body>"
            '<note type="other" othertype="wichtig">'
            '<p otherprops="note-ueberschrift">Bitte beachten Sie: </p>'
            "<p>Bitte informieren Sie sich rechtzeitig.</p>"
            "</note></body></topic>"
        )
        item = _xml_item(xml, {"brochure_number": "B16", "name": "Vorsicht, Grenze!"})

        converted = _run_chain(item, dita_to_html(), text_to_md())
        body = converted[0].data_object.data

        assert isinstance(body, str)
        assert "**Bitte beachten Sie:**" in body
        assert "Bitte beachten Sie::" not in body
        assert "Bitte informieren Sie sich rechtzeitig." in body

    def test_unbekannt_newsletter_note_has_no_synthetic_heading(self):
        xml = (
            "<topic><title>Die richtige Altersrente für Sie</title><body>"
            '<note type="other" othertype="unbekannt">'
            "<p>Wenn Sie monatlich über neue Broschüren informiert werden möchten, "
            "können Sie unseren Newsletter abonnieren.</p>"
            "</note></body></topic>"
        )
        item = _xml_item(xml, {"brochure_number": "B03", "name": "Die richtige Altersrente für Sie"})

        converted = _run_chain(item, dita_to_html(), text_to_md())
        body = converted[0].data_object.data

        assert isinstance(body, str)
        assert "Wenn Sie monatlich über neue Broschüren informiert werden möchten" in body
        assert "**Unbekannt:**" not in body
        assert "Unbekannt" not in body

    def test_note_chunk_has_no_frontmatter_and_keeps_metadata(self):
        xml = (
            "<topic><title>Beitragszahlung</title><body>"
            "<section><title>Beitragsberechnung</title>"
            '<note type="other" othertype="wichtig"><p>Zahlen Sie Ihre Beiträge rechtzeitig ein.</p></note>'
            "</section></body></topic>"
        )
        item = _xml_item(xml, {"brochure_number": "B34", "name": "Beitragszahlung"}, name="B34")

        extracted = extract_dita_notes().apply(item)
        assert len(extracted) == 2  # original passthrough + one note
        note_item = extracted[1]
        assert note_item.data_object.metadata["chunk_type"] == "note"

        chunks = _run_chain(note_item, dita_to_html(), text_to_md(), chunk_markdown())

        assert len(chunks) == 1
        body = chunks[0].data_object.data
        assert isinstance(body, str)  # Narrow DataObject.data for ty before string operations.
        assert_no_frontmatter(body)
        assert "chunk_type:" not in body  # metadata never leaks into the body
        assert chunks[0].data_object.metadata["chunk_type"] == "note"
        assert chunks[0].data_object.metadata["brochure_number"] == "B34"


class TestTablePathContract:

    def test_table_chunk_has_no_frontmatter_and_keeps_metadata(self):
        xml = (
            "<topic><title>Beitragssätze</title><body>"
            "<section><title>Übersicht</title>"
            '<p otherprops="note-ueberschrift">Beitragssätze 2024:</p>'
            '<table><tgroup cols="2"><tbody>'
            "<row><entry>Jahr</entry><entry>Satz</entry></row>"
            "<row><entry>2024</entry><entry>18,6 %</entry></row>"
            "</tbody></tgroup></table>"
            "</section></body></topic>"
        )
        item = _xml_item(xml, {"brochure_number": "B04", "name": "Beitragssätze"}, name="B04")

        extracted = extract_dita_tables().apply(item)
        assert len(extracted) == 2  # original passthrough + one table
        table_item = extracted[1]
        assert table_item.data_object.metadata["chunk_type"] == "table"

        chunks = _run_chain(table_item, dita_to_html(), text_to_md(), chunk_markdown())

        assert len(chunks) == 1
        body = chunks[0].data_object.data
        assert isinstance(body, str)  # Narrow DataObject.data for ty before string operations.
        assert_no_frontmatter(body)
        assert "chunk_type:" not in body
        assert chunks[0].data_object.metadata["chunk_type"] == "table"
        assert chunks[0].data_object.metadata["brochure_number"] == "B04"


class TestFaqPathContract:

    def test_faq_body_starts_with_heading_and_keeps_metadata(self):
        with patch("etl.transform.filter_html.load_brochure_url_mapping", return_value=_FAQ_MAPPING):
            faq_transform = prepare_faq_html()

        item = PipelineItem(
            name="faq-a-und-b.html",
            data_object=DataObject(name="faq-a-und-b.html", data=_FAQ_HTML, data_type=DataType.HTML, metadata={}),
        )

        prepared = faq_transform.apply(item)
        assert len(prepared) == 1  # one document-bearing question (boundary skipped)

        chunks = _run_chain(prepared[0], text_to_md())
        assert len(chunks) == 1
        body = chunks[0].data_object.data
        assert isinstance(body, str)  # Narrow DataObject.data for ty before string operations.

        assert_no_frontmatter(body)
        assert body == body.strip()
        assert body.startswith("#")
        assert "Wie beantrage ich meine Rente?" in body

        metadata = chunks[0].data_object.metadata
        assert metadata["name"] == "FAQ Antragstellung"
        assert metadata["brochure_number"] == "faq-a-und-b"
        assert metadata["brochure_url"] == f"{_FAQ_URL}#content-0"
