
import pytest

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.convert_to_html import dita_to_html
from etl.transform.convert_to_md import text_to_md


@pytest.fixture
def transform():
    return dita_to_html()


@pytest.fixture
def sample_dita_xml():
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE concept PUBLIC "-//OASIS//DTD DITA Concept//EN" "concept.dtd">
<concept id="test-concept">
  <title>Test Document</title>
  <prolog>
    <metadata>
      <category>test-category</category>
      <keywords>
        <keyword>test</keyword>
        <keyword>sample</keyword>
      </keywords>
    </metadata>
  </prolog>
  <conbody>
    <p>This is a <b>bold</b> paragraph with <i>italic</i> and <u>underline</u> text.</p>
    <p>See <xref href="other-topic.dita" scope="external">Other Topic</xref> for more info.</p>
    <p>See also <xref href="#test-section"/> below.</p>
    <ul>
      <li>Item one</li>
      <li>Item two</li>
    </ul>
    <ol>
      <li>First item</li>
      <li>Second item</li>
    </ol>
    <ul>
      <li>Parent Item 1
        <ul>
          <li>Child Item 1.1</li>
          <li>Child Item 1.2</li>
        </ul>
      </li>
      <li>Parent Item 2</li>
    </ul>
    <section id="test-section">
      <title>Section Title</title>
      <p>Section content.</p>
    </section>
    <note type="warning">This is a warning note.</note>
    <note type="tip">This is a tip note.</note>
    <note>This is a default note.</note>
    <table>
      <tgroup cols="2">
        <thead>
          <row>
            <entry>Header 1</entry>
            <entry>Header 2</entry>
          </row>
        </thead>
        <tbody>
          <row>
            <entry>Cell 1</entry>
            <entry>Cell 2</entry>
          </row>
        </tbody>
      </tgroup>
    </table>
  </conbody>
</concept>
"""


def make_pipeline_item(data: bytes | str, name: str = "test-document") -> PipelineItem:
    return PipelineItem(
        name=name,
        data_object=DataObject(
            name=name,
            data=data,
            data_type=DataType.XML,
            metadata={"name": name},
        ),
    )


class TestDitaToHtmlApply:

    def test_apply_returns_list_of_pipeline_items(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], PipelineItem)

    def test_output_type_is_html(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        assert result.data_object.data_type == DataType.HTML

    def test_output_content_is_string(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        assert isinstance(result.data_object.data, str)

    def test_preserves_metadata(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        assert result.data_object.metadata["name"] == "test-document"


class TestParagraphRendering:

    def test_renders_paragraph_as_html_p_tag(self, transform: dita_to_html):
        xml = '<?xml version="1.0"?><concept id="t"><title>T</title><conbody><p>This is a test paragraph.</p></conbody></concept>'
        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)
        assert "<p>This is a test paragraph.</p>" in data

    def test_renders_nested_inline_elements(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "<b>bold</b>" in data
        assert "<i>italic</i>" in data


class TestListRendering:

    def test_renders_unordered_list(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "<ul>" in data
        assert "<li>Item one</li>" in data
        assert "<li>Item two</li>" in data

    def test_renders_ordered_list(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "<ol>" in data
        assert "<li>First item</li>" in data
        assert "<li>Second item</li>" in data

    def test_renders_nested_lists(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "<li>Parent Item 1" in data
        assert "<li>Child Item 1.1</li>" in data
        assert "<li>Child Item 1.2</li>" in data


class TestSectionRendering:

    def test_renders_section_with_title(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "<h2>Section Title</h2>" in data

    def test_renders_section_content(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "<p>Section content.</p>" in data


class TestNoteRendering:

    def test_author_heading_with_trailing_whitespace_has_one_colon(self, transform: dita_to_html):
        xml = (
            "<topic><title>Vorsicht, Grenze!</title><body>"
            '<note type="other" othertype="wichtig">'
            '<p otherprops="note-ueberschrift">Bitte beachten Sie: </p>'
            "<p>Bitte informieren Sie sich rechtzeitig.</p>"
            "</note></body></topic>"
        )

        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)

        assert "<strong>Bitte beachten Sie:</strong>" in data
        assert "Bitte beachten Sie::" not in data
        assert "<p>Bitte informieren Sie sich rechtzeitig.</p>" in data

    def test_unbekannt_without_author_heading_has_no_fabricated_label(self, transform: dita_to_html):
        xml = (
            "<topic><title>Newsletter</title><body>"
            '<note type="other" othertype="unbekannt">'
            "<p>Wenn Sie monatlich über neue Broschüren informiert werden möchten.</p>"
            "</note></body></topic>"
        )

        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)

        assert "<aside class='note note-other'>" in data
        assert "<p>Wenn Sie monatlich über neue Broschüren informiert werden möchten.</p>" in data
        assert "<strong>" not in data
        assert "Unbekannt" not in data

    def test_unbekannt_with_author_heading_keeps_heading(self, transform: dita_to_html):
        xml = (
            "<topic><title>Beispiel</title><body>"
            '<note type="other" othertype="unbekannt">'
            '<p otherprops="note-ueberschrift">Beispiel: </p>'
            "<p>Ein Beispieltext.</p>"
            "</note></body></topic>"
        )

        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)

        assert "<strong>Beispiel:</strong>" in data
        assert "Beispiel::" not in data
        assert "Unbekannt" not in data

    def test_renders_note_with_type_class(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "class='note note-warning'" in data
        assert "class='note note-tip'" in data

    def test_renders_default_note(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "class='note note-note'" in data


class TestTableRendering:

    def test_renders_table_structure(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "<table>" in data
        assert "<tr>" in data
        assert "</table>" in data

    def test_first_row_renders_as_th(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "<th>Header 1</th>" in data
        assert "<th>Header 2</th>" in data

    def test_remaining_rows_render_as_td(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "<td>Cell 1</td>" in data
        assert "<td>Cell 2</td>" in data

    def test_table_title_renders_as_h3(self, transform: dita_to_html):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<topic><title>T</title><body>
<table><title>Überleitung in Pflegegrade</title>
  <tgroup cols="2"><tbody>
    <row><entry>Pflegegrad</entry><entry>Bedeutung</entry></row>
    <row><entry>1</entry><entry>gering</entry></row>
  </tbody></tgroup>
</table>
</body></topic>""".encode()
        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)
        assert "<h3>Überleitung in Pflegegrade</h3>" in data
        assert data.index("<h3>Überleitung in Pflegegrade</h3>") < data.index("<table>")

    def test_table_without_title_renders_without_h3(self, transform: dita_to_html):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<topic><title>T</title><body>
<table><title></title>
  <tgroup cols="2"><tbody>
    <row><entry>A</entry><entry>B</entry></row>
    <row><entry>1</entry><entry>2</entry></row>
  </tbody></tgroup>
</table>
</body></topic>"""
        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)
        assert "<h3></h3>" not in data


class TestSingleColumnLayoutTables:

    FLOW_TABLE = """<?xml version="1.0" encoding="UTF-8"?>
<topic><title>T</title><body>
<table>
  <tgroup cols="1"><tbody>
    <row><entry><p><b>Antrag</b></p></entry></row>
    <row><entry><p>Hilfe bekommen Sie bei den</p></entry></row>
    <row><entry><ul>
      <li><p>Rentenversicherungstraegern</p></li>
      <li><p>Beratungsstellen</p></li>
    </ul></entry></row>
    <row><entry><p><b>↓</b></p></entry></row>
    <row><entry><p><b>Entscheidung</b></p></entry></row>
    <row><entry><p>Der Dienst prueft den Antrag.</p></entry></row>
  </tbody></tgroup>
</table>
</body></topic>""".encode()

    def test_linearizes_layout_instead_of_rendering_table(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.FLOW_TABLE))[0].data_object.data)
        assert "<table>" not in data
        assert "<th>" not in data
        assert "<td>" not in data

    def test_promotes_step_labels_and_drops_arrow_rows(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.FLOW_TABLE))[0].data_object.data)
        assert "<h3>Antrag</h3>" in data
        assert "<h3>Entscheidung</h3>" in data
        assert "↓" not in data

    def test_preserves_cell_internal_list_as_real_list(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.FLOW_TABLE))[0].data_object.data)
        assert "<p>Hilfe bekommen Sie bei den</p>" in data
        assert "<ul>" in data
        assert "<li><p>Rentenversicherungstraegern</p>" in data
        assert "<li><p>Beratungsstellen</p>" in data

    def test_markdown_keeps_steps_and_nested_bullets(self, transform: dita_to_html):
        html_item = transform.apply(make_pipeline_item(self.FLOW_TABLE))[0]
        markdown = str(text_to_md().apply(html_item)[0].data_object.data)
        assert "### Antrag" in markdown
        assert "* Rentenversicherungstraegern" in markdown
        assert "* Beratungsstellen" in markdown
        assert "| Antrag |" not in markdown
        assert "↓" not in markdown


class TestSpanAwareTables:

    # A two-row header: col3 spans col3-col4 ("namest/nameend") and splits into
    # Jahr/Monat below; the outer columns span both header rows ("morerows").
    # The last body row spans every column (a footnote).
    SPANNED_TABLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<topic><title>T</title><body>
<table><title>Anhebung</title>
<tgroup cols="5">
<colspec colname="col1"/><colspec colname="col2"/><colspec colname="col3"/>
<colspec colname="col4"/><colspec colname="col5"/>
<thead>
<row>
<entry colname="col1" morerows="1"><p>Geburtsjahr</p></entry>
<entry colname="col2" morerows="1"><p>Anhebung</p></entry>
<entry namest="col3" nameend="col4"><p>Rentenbeginn</p></entry>
<entry colname="col5" morerows="1"><p>Abschlag</p></entry>
</row>
<row>
<entry colname="col3"><p>Jahr</p></entry>
<entry colname="col4"><p>Monat</p></entry>
</row>
</thead>
<tbody>
<row>
<entry colname="col1"><p>1959</p></entry><entry colname="col2"><p>14</p></entry>
<entry colname="col3"><p>66</p></entry><entry colname="col4"><p>2</p></entry>
<entry colname="col5"><p>11,4</p></entry>
</row>
<row><entry namest="col1" nameend="col5"><p>Vertrauensschutz gilt fuer den Bergbau.</p></entry></row>
</tbody>
</tgroup>
</table>
</body></topic>"""

    def test_multirow_header_merged_per_column(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.SPANNED_TABLE))[0].data_object.data)
        assert data.count("<th>") == 5
        assert "<th>Rentenbeginn Jahr</th>" in data
        assert "<th>Rentenbeginn Monat</th>" in data
        assert "<th>Geburtsjahr</th>" in data
        assert "<th>Abschlag</th>" in data

    def test_data_row_is_rectangular_and_lossless(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.SPANNED_TABLE))[0].data_object.data)
        # Exactly one body row of 5 cells (the footnote row is not a row).
        assert data.count("<td>") == 5
        assert "11,4" in data

    def test_full_width_row_lifted_as_paragraph(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.SPANNED_TABLE))[0].data_object.data)
        assert "<p>Vertrauensschutz gilt fuer den Bergbau.</p>" in data
        assert data.index("</table>") < data.index("Vertrauensschutz")

    # A body cell spans two rows (morerows); a full-width band sits between the
    # spanned row and the next data row. The band must still count against the
    # span, otherwise the span survives one row too long and shifts the trailing
    # value out of the first column.
    ROWSPAN_ACROSS_BAND = b"""<?xml version="1.0" encoding="UTF-8"?>
<topic><title>T</title><body>
<table>
<tgroup cols="2"><colspec colname="col1"/><colspec colname="col2"/>
<thead><row><entry colname="col1"><p>A</p></entry><entry colname="col2"><p>B</p></entry></row></thead>
<tbody>
<row><entry morerows="1"><p>x</p></entry><entry><p>1</p></entry></row>
<row><entry namest="col1" nameend="col2"><p>Note</p></entry></row>
<row><entry><p>2</p></entry></row>
</tbody>
</tgroup>
</table>
</body></topic>"""

    def test_rowspan_not_extended_by_fullwidth_band(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.ROWSPAN_ACROSS_BAND))[0].data_object.data)
        # The mid-table band is kept in place (a row), not lifted out.
        assert "<td><p>Note</p></td>" in data
        # The value below stays in the first column (col0), not pushed right by a
        # row span that should already be exhausted.
        assert "<td><p>2</p></td>\n<td></td>" in data

    # Two section headings ("Kleine"/"Große") each introduce the rows beneath
    # them; a genuine footnote trails the table. There is no explicit <thead>.
    MULTI_SECTION = b"""<?xml version="1.0" encoding="UTF-8"?>
<topic><title>T</title><body>
<table>
<tgroup cols="3"><colspec colname="col1"/><colspec colname="col2"/><colspec colname="col3"/>
<tbody>
<row><entry namest="col1" nameend="col3"><p>Kleine Witwenrente</p></entry></row>
<row><entry colname="col2"><p>erstes Kind</p></entry><entry colname="col3"><p>weitere</p></entry></row>
<row><entry colname="col2"><p>37,08</p></entry><entry colname="col3"><p>18,54</p></entry></row>
<row><entry namest="col1" nameend="col3"><p>Grosse Witwenrente</p></entry></row>
<row><entry colname="col2"><p>81,57</p></entry><entry colname="col3"><p>40,79</p></entry></row>
<row><entry namest="col1" nameend="col3"><p>* bei Kindererziehung</p></entry></row>
</tbody>
</tgroup>
</table>
</body></topic>"""

    def test_midtable_section_headings_kept_in_place(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.MULTI_SECTION))[0].data_object.data)
        table = data[: data.index("</table>")]
        # Both headings render as in-place cells, not relocated paragraphs...
        assert "<td><p>Kleine Witwenrente</p></td>" in table
        assert "<td><p>Grosse Witwenrente</p></td>" in table
        # ...in document order, each ahead of the values it labels.
        assert (
            table.index("Kleine Witwenrente")
            < table.index("37,08")
            < table.index("Grosse Witwenrente")
            < table.index("81,57")
        )
        # A full-width first row is not promoted to the table header.
        assert "<th>Kleine Witwenrente</th>" not in data

    def test_trailing_fullwidth_row_still_lifted(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.MULTI_SECTION))[0].data_object.data)
        assert data.index("</table>") < data.index("* bei Kindererziehung")


class TestHeaderAndColumnCleanup:

    # "Kleine Witwenrente" spans all three columns and has NO sub-header row.
    WIDE_HEADER = b"""<?xml version="1.0" encoding="UTF-8"?>
<topic><title>T</title><body>
<table><title>Witwenrente</title>
<tgroup cols="3">
<colspec colname="col1"/><colspec colname="col2"/><colspec colname="col3"/>
<thead>
<row><entry namest="col1" nameend="col3"><p>Kleine Witwenrente</p></entry></row>
</thead>
<tbody>
<row><entry colname="col1"><p>davon</p></entry><entry colname="col2"><p>erstes Kind</p></entry><entry colname="col3"><p>weitere</p></entry></row>
</tbody>
</tgroup>
</table>
</body></topic>"""

    # Middle column (col2) has no entry anywhere -> spacer; col1 has only a body
    # value (row-label column, empty header).
    SPACER_AND_ROWLABEL = b"""<?xml version="1.0" encoding="UTF-8"?>
<topic><title>T</title><body>
<table>
<tgroup cols="3">
<colspec colname="col1"/><colspec colname="col2"/><colspec colname="col3"/>
<thead>
<row><entry colname="col3"><p>Betrag</p></entry></row>
</thead>
<tbody>
<row><entry colname="col1"><p>Miete</p></entry><entry colname="col3"><p>500</p></entry></row>
</tbody>
</tgroup>
</table>
</body></topic>"""

    def test_wide_header_label_not_repeated(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.WIDE_HEADER))[0].data_object.data)
        assert data.count("Kleine Witwenrente") == 1
        # the spanned columns still exist (they carry body values) but with blank headers
        assert data.count("<th>") == 3
        assert "<th></th>" in data

    def test_empty_spacer_column_dropped(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.SPACER_AND_ROWLABEL))[0].data_object.data)
        # col2 (spacer) dropped -> 2 columns remain
        assert data.count("<th>") == 2
        assert "<th>Betrag</th>" in data

    def test_row_label_column_kept(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.SPACER_AND_ROWLABEL))[0].data_object.data)
        assert "Miete" in data
        assert "500" in data

    # A blank spacer row (empty <p> cells) sits between two data rows.
    EMPTY_ROW = b"""<?xml version="1.0" encoding="UTF-8"?>
<topic><title>T</title><body>
<table>
<tgroup cols="2"><colspec colname="col1"/><colspec colname="col2"/>
<thead><row><entry colname="col1"><p>A</p></entry><entry colname="col2"><p>B</p></entry></row></thead>
<tbody>
<row><entry colname="col1"><p>1</p></entry><entry colname="col2"><p>2</p></entry></row>
<row><entry colname="col1"><p></p></entry><entry colname="col2"><p></p></entry></row>
<row><entry colname="col1"><p>3</p></entry><entry colname="col2"><p>4</p></entry></row>
</tbody>
</tgroup>
</table>
</body></topic>"""

    def test_blank_spacer_rows_dropped(self, transform: dita_to_html):
        data = str(transform.apply(make_pipeline_item(self.EMPTY_ROW))[0].data_object.data)
        # Two data rows (1|2 and 3|4) survive -> 4 body cells; the blank row is gone.
        assert data.count("<td>") == 4


class TestInlineElements:

    def test_renders_inline_elements(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "<b>bold</b>" in data
        assert "<i>italic</i>" in data
        assert "<u>underline</u>" in data

    def test_renders_external_xref_as_anchor(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "<a href='other-topic.dita'>Other Topic</a>" in data

    def test_renders_local_xref_as_resolved_text(self, transform: dita_to_html, sample_dita_xml: bytes):
        result = transform.apply(make_pipeline_item(sample_dita_xml))[0]
        data = str(result.data_object.data)
        assert "Section Title" in data
        assert "<a href='#test-section'>" not in data


class TestNewSchemaStructure:

    def test_sectiondiv_with_title_renders_h3(self, transform: dita_to_html):
        xml = (
            '<?xml version="1.0"?>'
            '<topic id="t"><title>T</title><body>'
            "<sectiondiv><title>SubA</title><p>content A</p></sectiondiv>"
            "</body></topic>"
        )
        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)
        assert "<h3>SubA</h3>" in data
        assert "<p>content A</p>" in data

    def test_paragraph_with_subheading_otherprops_renders_h3(self, transform: dita_to_html):
        xml = (
            '<?xml version="1.0"?>'
            '<topic id="t"><title>T</title><body>'
            "<sectiondiv>"
            '<p otherprops="zwischenueberschrift">Subheading text</p>'
            "<p>Body paragraph.</p>"
            "</sectiondiv>"
            "</body></topic>"
        )
        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)
        assert "<h3>Subheading text</h3>" in data
        assert "<p>Body paragraph.</p>" in data
        assert "<p>Subheading text</p>" not in data

    def test_bodydiv_renders_as_div_with_class(self, transform: dita_to_html):
        xml = (
            '<?xml version="1.0"?>'
            '<topic id="t"><title>T</title><body>'
            '<bodydiv otherprops="vorwort"><p>Foreword.</p></bodydiv>'
            "</body></topic>"
        )
        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)
        assert "body-div" in data
        assert "vorwort" in data
        assert "<p>Foreword.</p>" in data

    def test_section_otherprops_emits_class(self, transform: dita_to_html):
        xml = (
            '<?xml version="1.0"?>'
            '<topic id="t"><title>T</title><body>'
            '<section otherprops="vorwort"><title>V</title><p>x</p></section>'
            "</body></topic>"
        )
        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)
        assert "section-vorwort" in data
        assert "<h2>V</h2>" in data

    def test_normal_paragraph_unchanged(self, transform: dita_to_html):
        xml = '<?xml version="1.0"?><topic id="t"><title>T</title><body><p>Normal.</p></body></topic>'
        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)
        assert "<p>Normal.</p>" in data
        assert "<h3>" not in data


class TestNewInlineElements:

    @pytest.mark.parametrize(
        "tag, inner, expected",
        [
            ("sub", "2", "<sub>2</sub>"),
            ("sup", "3", "<sup>3</sup>"),
            ("tt", "x", "<code>x</code>"),
            ("ph", "x", "<span>x</span>"),
        ],
    )
    def test_inline_tag_rendering(self, transform: dita_to_html, tag, inner, expected):
        xml = (
            f'<?xml version="1.0"?>'
            f'<topic id="t"><title>T</title><body>'
            f"<p>foo<{tag}>{inner}</{tag}>bar</p>"
            f"</body></topic>"
        )
        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)
        assert expected in data


class TestErrorHandling:

    def test_handles_invalid_xml(self, transform: dita_to_html):
        with pytest.raises(ValueError):
            transform.apply(make_pipeline_item(b"<invalid><xml>"))

    def test_handles_empty_content(self, transform):
        with pytest.raises(ValueError):
            transform.apply(make_pipeline_item(b""))

    def test_handles_unknown_elements(self, transform: dita_to_html):
        xml = '<?xml version="1.0"?><concept id="t"><title>T</title><conbody><unknown>Ignored.</unknown><p>Visible.</p></conbody></concept>'
        result = transform.apply(make_pipeline_item(xml))[0]
        data = str(result.data_object.data)
        assert "<p>Visible.</p>" in data
        assert "Ignored" not in data


class TestEmptyPageReferenceResolution:

    def test_local_chapter_xref_resolves_to_plain_title_without_auto_quotes(
        self, transform: dita_to_html, sample_dita_xml: bytes
    ):
        """The single-segment `#test-section` xref now renders its title as plain text.

        Previously the empty xref emitted nothing; the resolver + rewriter turn it
        into the target section title with no auto-added quotes (the source, not
        the transform, supplies any „ “).
        """
        data = str(transform.apply(make_pipeline_item(sample_dita_xml))[0].data_object.data)
        assert "<p>See also Section Title below.</p>" in data
        assert '"Section Title"' not in data  # no auto-quotes around the resolved title

    def test_topic_qualified_page_xref_removed_as_grammatical_prose(self, transform: dita_to_html):
        xml = (
            '<?xml version="1.0"?>'
            '<topic id="B1"><title>T</title><body>'
            '<p>Mehr dazu lesen Sie ab Seite <xref scope="local" href="#B1/para-x"/>.</p>'
            '<p id="para-x">Zieltext.</p>'
            "</body></topic>"
        )
        data = str(transform.apply(make_pipeline_item(xml))[0].data_object.data)
        assert "<p>Mehr dazu lesen Sie.</p>" in data
        assert "Seite" not in data.split("<p>Mehr dazu")[1].split("</p>")[0]

    def test_topic_qualified_chapter_xref_resolves_to_section_title(self, transform: dita_to_html):
        xml = (
            '<?xml version="1.0"?>'
            '<topic id="B1"><title>T</title><body>'
            '<p>Lesen Sie unser Kapitel „<xref scope="local" href="#B1/sec-x"/>“.</p>'
            '<section id="sec-x"><title>Wichtige Hinweise</title><p>Inhalt.</p></section>'
            "</body></topic>"
        )
        data = str(transform.apply(make_pipeline_item(xml))[0].data_object.data)
        assert "<p>Lesen Sie unser Kapitel „Wichtige Hinweise“.</p>" in data

    def test_external_xref_with_page_cue_is_untouched(self, transform: dita_to_html):
        xml = (
            '<?xml version="1.0"?>'
            '<topic id="B1"><title>T</title><body>'
            '<p>Mehr auf Seite <xref scope="external" href="https://drv.example">Portal</xref>.</p>'
            "</body></topic>"
        )
        data = str(transform.apply(make_pipeline_item(xml))[0].data_object.data)
        assert "<a href='https://drv.example'>Portal</a>" in data
