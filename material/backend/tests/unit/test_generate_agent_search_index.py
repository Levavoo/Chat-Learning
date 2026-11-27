import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from generate_agent_search_index import (
    _clean_text,
    _extract_section_content,
    _extract_subsections,
    _extract_text,
    _get_data_value,
    _split_large_sections,
    generate_missing_keywords,
    generate_summaries,
    parse_all_xml,
    parse_xml,
    write_documents,
    write_index,
)

MINIMAL_XML = """\
<?xml version='1.0' encoding='utf-8'?>
<topic id="test" xml:lang="de-DE">
  <title>Test Broschüre</title>
  <prolog>
    <metadata>
      <category>Rente</category>
      <keywords>
        <keyword>Altersrente</keyword>
        <keyword>Wartezeit</keyword>
      </keywords>
    </metadata>
    <data name="broschrennummer" value="T01"/>
    <data name="auflage" value="5. Auflage"/>
    <data name="veroeffentlichung" value="3/2025"/>
  </prolog>
  <body>
    <section>
      <ul><li><p>Inhaltsverzeichnis Eintrag</p></li></ul>
    </section>
    <section>
      <title>Erster Abschnitt</title>
      <p>Absatz eins.</p>
      <p>Absatz zwei.</p>
    </section>
    <section>
      <title>Zweiter Abschnitt</title>
      <p>Noch ein Absatz.</p>
      <ul>
        <li><p>Punkt A</p></li>
        <li><p>Punkt B</p></li>
      </ul>
      <note type="other" othertype="tip">
        <p>Unser Tipp:</p>
        <p>Beratung nutzen.</p>
      </note>
    </section>
  </body>
</topic>
"""

NO_KEYWORDS_XML = """\
<?xml version='1.0' encoding='utf-8'?>
<topic id="test2" xml:lang="de-DE">
  <title>Ohne Keywords</title>
  <prolog>
    <metadata><category>Service</category></metadata>
    <data name="broschrennummer" value="T02"/>
    <data name="auflage" value="1. Auflage"/>
    <data name="veroeffentlichung" value="1/2025"/>
  </prolog>
  <body>
    <section><title>Einleitung</title><p>Text.</p></section>
  </body>
</topic>
"""

SPACE_ID_XML = """\
<?xml version='1.0' encoding='utf-8'?>
<topic id="test3" xml:lang="de-DE">
  <title>Space ID</title>
  <prolog>
    <metadata><category>Prävention</category></metadata>
    <data name="broschrennummer" value="FB 28"/>
    <data name="auflage" value="8. Auflage"/>
    <data name="veroeffentlichung" value="7/2024"/>
  </prolog>
  <body>
    <section><title>Inhalt</title><p>Text.</p></section>
  </body>
</topic>
"""


@pytest.fixture()
def xml_dir(tmp_path):
    (tmp_path / "T01.xml").write_text(MINIMAL_XML, encoding="utf-8")
    (tmp_path / "T02.xml").write_text(NO_KEYWORDS_XML, encoding="utf-8")
    (tmp_path / "FB28.xml").write_text(SPACE_ID_XML, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def duplicate_dir(tmp_path):
    (tmp_path / "B38_new.xml").write_text(
        MINIMAL_XML.replace("T01", "B38").replace("Test Broschüre", "Doc A"), encoding="utf-8"
    )
    (tmp_path / "B38_old.xml").write_text(
        MINIMAL_XML.replace("T01", "B38").replace("Test Broschüre", "Doc B"), encoding="utf-8"
    )
    return tmp_path


class TestCleanText:
    def test_removes_soft_hyphens(self):
        assert _clean_text("Renten\xadversicherung") == "Rentenversicherung"

    def test_collapses_whitespace(self):
        assert _clean_text("a   b\t\tc") == "a b c"

    def test_strips(self):
        assert _clean_text("  hello  ") == "hello"


class TestExtractText:
    def test_extracts_nested_text(self):
        el = ET.fromstring("<p>Hello <b>world</b> end</p>")
        assert _extract_text(el) == "Hello world end"


class TestGetDataValue:
    def test_finds_value(self):
        root = ET.fromstring('<root><data name="foo" value="bar"/></root>')
        assert _get_data_value(root, "foo") == "bar"

    def test_missing_returns_empty(self):
        root = ET.fromstring("<root/>")
        assert _get_data_value(root, "foo") == ""


class TestExtractSectionContent:
    def test_paragraphs(self):
        section = ET.fromstring("<section><title>T</title><p>A</p><p>B</p></section>")
        assert _extract_section_content(section) == "A\nB"

    def test_unordered_list(self):
        section = ET.fromstring("<section><ul><li><p>X</p></li><li><p>Y</p></li></ul></section>")
        assert _extract_section_content(section) == "- X\n- Y"

    def test_ordered_list(self):
        section = ET.fromstring("<section><ol><li><p>A</p></li><li><p>B</p></li></ol></section>")
        assert _extract_section_content(section) == "1. A\n2. B"

    def test_note(self):
        section = ET.fromstring("<section><note><p>Tipp:</p><p>Details.</p></note></section>")
        assert _extract_section_content(section) == "Hinweis: Tipp: Details."

    def test_skips_title(self):
        section = ET.fromstring("<section><title>Skip me</title><p>Keep me</p></section>")
        assert _extract_section_content(section) == "Keep me"


class TestParseXml:
    def test_extracts_metadata(self, xml_dir):
        doc = parse_xml(xml_dir / "T01.xml")
        assert doc["doc_id"] == "T01"
        assert doc["title"] == "Test Broschüre"
        assert doc["category"] == "Rente"
        assert doc["edition"] == "5. Auflage"
        assert doc["published"] == "3/2025"

    def test_extracts_keywords(self, xml_dir):
        doc = parse_xml(xml_dir / "T01.xml")
        assert doc["keywords"] == ["Altersrente", "Wartezeit"]

    def test_empty_keywords(self, xml_dir):
        doc = parse_xml(xml_dir / "T02.xml")
        assert doc["keywords"] == []

    def test_skips_untitled_sections(self, xml_dir):
        doc = parse_xml(xml_dir / "T01.xml")
        titles = [s["title"] for s in doc["sections"]]
        assert "Erster Abschnitt" in titles
        assert all(t for t in titles)

    def test_section_content(self, xml_dir):
        doc = parse_xml(xml_dir / "T01.xml")
        first = next(s for s in doc["sections"] if s["title"] == "Erster Abschnitt")
        assert "Absatz eins." in first["content"]
        assert "Absatz zwei." in first["content"]

    def test_section_with_list_and_note(self, xml_dir):
        doc = parse_xml(xml_dir / "T01.xml")
        second = next(s for s in doc["sections"] if s["title"] == "Zweiter Abschnitt")
        assert "- Punkt A" in second["content"]
        assert "- Punkt B" in second["content"]
        assert "Hinweis:" in second["content"]

    def test_strips_spaces_from_doc_id(self, xml_dir):
        doc = parse_xml(xml_dir / "FB28.xml")
        assert doc["doc_id"] == "FB28"


class TestParseAllXml:
    def test_parses_all_files(self, xml_dir):
        docs = parse_all_xml(xml_dir)
        assert len(docs) == 3

    def test_handles_duplicate_doc_ids(self, duplicate_dir):
        docs = parse_all_xml(duplicate_dir)
        ids = [d["doc_id"] for d in docs]
        assert "B38" in ids
        assert "B38_v2" in ids

    def test_raises_on_empty_dir(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_all_xml(tmp_path)


class TestGenerateMissingKeywords:
    def test_skips_docs_with_keywords(self):
        client = MagicMock()
        docs = [{"doc_id": "T01", "keywords": ["a"], "sections": [], "title": "T", "category": "R"}]
        generate_missing_keywords(client, "model", docs)
        client.converse.assert_not_called()

    def test_generates_for_empty_keywords(self):
        client = MagicMock()
        client.converse.return_value = {"output": {"message": {"content": [{"text": '["Kw1", "Kw2", "Kw3"]'}]}}}
        docs = [
            {
                "doc_id": "T01",
                "keywords": [],
                "sections": [{"title": "S", "content": "C"}],
                "title": "T",
                "category": "R",
            }
        ]
        generate_missing_keywords(client, "model", docs)
        assert docs[0]["keywords"] == ["Kw1", "Kw2", "Kw3"]

    def test_handles_llm_error_gracefully(self):
        client = MagicMock()
        client.converse.side_effect = Exception("API error")
        docs = [
            {
                "doc_id": "T01",
                "keywords": [],
                "sections": [{"title": "S", "content": "C"}],
                "title": "T",
                "category": "R",
            }
        ]
        generate_missing_keywords(client, "model", docs)
        assert docs[0]["keywords"] == []


class TestGenerateSummaries:
    def test_applies_summaries(self):
        client = MagicMock()
        client.converse.return_value = {
            "output": {"message": {"content": [{"text": '{"T01": "Summary one", "T02": "Summary two"}'}]}}
        }
        docs = [
            {"doc_id": "T01", "title": "A", "category": "R", "keywords": [], "sections": [{"title": "S"}]},
            {"doc_id": "T02", "title": "B", "category": "S", "keywords": [], "sections": [{"title": "S"}]},
        ]
        generate_summaries(client, "model", docs)
        assert docs[0]["summary"] == "Summary one"
        assert docs[1]["summary"] == "Summary two"

    def test_handles_llm_error_gracefully(self):
        client = MagicMock()
        client.converse.side_effect = Exception("API error")
        docs = [{"doc_id": "T01", "title": "A", "category": "R", "keywords": [], "sections": [{"title": "S"}]}]
        generate_summaries(client, "model", docs)
        assert docs[0]["summary"] == ""


class TestWriteIndex:
    def test_writes_valid_json(self, tmp_path):
        docs = [
            {
                "doc_id": "T01",
                "title": "T",
                "category": "R",
                "edition": "1",
                "published": "1/25",
                "keywords": ["k"],
                "sections": [{"title": "S", "content": "C"}],
                "summary": "Sum",
            }
        ]
        write_index(docs, tmp_path)
        index = json.loads((tmp_path / "index.json").read_text())
        assert len(index["documents"]) == 1
        assert index["documents"][0]["doc_id"] == "T01"
        assert index["documents"][0]["sections"] == ["S"]
        assert "content" not in index["documents"][0]


class TestWriteDocuments:
    def test_writes_per_doc_files(self, tmp_path):
        docs = [
            {
                "doc_id": "T01",
                "title": "A",
                "category": "R",
                "edition": "1",
                "published": "1/25",
                "sections": [{"title": "S", "content": "C"}],
            },
            {
                "doc_id": "T02",
                "title": "B",
                "category": "S",
                "edition": "2",
                "published": "2/25",
                "sections": [{"title": "S2", "content": "C2"}],
            },
        ]
        write_documents(docs, tmp_path)
        assert (tmp_path / "documents" / "T01.json").exists()
        assert (tmp_path / "documents" / "T02.json").exists()

        doc = json.loads((tmp_path / "documents" / "T01.json").read_text())
        assert doc["sections"][0]["content"] == "C"
        assert doc["brochure_number"] == "T01"


class TestSplitLargeSections:
    def test_small_section_unchanged(self):
        sections = [{"title": "Short", "content": "Hello world"}]
        result = _split_large_sections(sections)
        assert result == sections

    def test_exactly_at_limit(self):
        content = "a" * 3000
        sections = [{"title": "Exact", "content": content}]
        result = _split_large_sections(sections)
        assert len(result) == 1
        assert result[0]["content"] == content

    def test_large_section_split_on_paragraphs(self):
        para1 = "A" * 2000
        para2 = "B" * 2000
        sections = [{"title": "Big", "content": f"{para1}\n{para2}"}]
        result = _split_large_sections(sections)
        assert len(result) == 2
        assert result[0]["title"] == "Big (Teil 1)"
        assert result[1]["title"] == "Big (Teil 2)"
        assert result[0]["content"] == para1
        assert result[1]["content"] == para2

    def test_single_paragraph_over_limit(self):
        """Single paragraph over limit cannot be split, stays as one."""
        content = "X" * 5000
        sections = [{"title": "Huge", "content": content}]
        result = _split_large_sections(sections)
        assert len(result) == 1
        assert result[0]["content"] == content

    def test_multiple_sections_mixed(self):
        sections = [
            {"title": "Small", "content": "short"},
            {"title": "Large", "content": "\n".join(["paragraph text here"] * 300)},
        ]
        result = _split_large_sections(sections)
        assert result[0]["title"] == "Small"
        assert len(result) > 2


class TestExtractSubsections:
    def test_no_titled_divs_returns_single_section(self):
        xml = "<section><title>Parent</title><p>Content here</p></section>"
        section = ET.fromstring(xml)
        result = _extract_subsections(section, "Parent")
        assert len(result) == 1
        assert result[0]["title"] == "Parent"
        assert "Content here" in result[0]["content"]

    def test_titled_divs_split_into_subsections(self):
        xml = """<section>
            <title>Parent</title>
            <p>Preamble text</p>
            <div><wintitle>Sub A</wintitle><p>Content A</p></div>
            <div><wintitle>Sub B</wintitle><p>Content B</p></div>
        </section>"""
        section = ET.fromstring(xml)
        result = _extract_subsections(section, "Parent")
        assert len(result) == 3
        assert result[0]["title"] == "Parent"
        assert "Preamble text" in result[0]["content"]
        assert result[1]["title"] == "Parent - Sub A"
        assert "Content A" in result[1]["content"]
        assert result[2]["title"] == "Parent - Sub B"
        assert "Content B" in result[2]["content"]

    def test_no_preamble(self):
        xml = """<section>
            <title>Parent</title>
            <div><wintitle>Only</wintitle><p>Content</p></div>
        </section>"""
        section = ET.fromstring(xml)
        result = _extract_subsections(section, "Parent")
        assert len(result) == 1
        assert result[0]["title"] == "Parent - Only"

    def test_untitled_div_goes_to_preamble(self):
        xml = """<section>
            <title>Parent</title>
            <div><p>Untitled div content</p></div>
            <div><wintitle>Titled</wintitle><p>Titled content</p></div>
        </section>"""
        section = ET.fromstring(xml)
        result = _extract_subsections(section, "Parent")
        assert len(result) == 2
        assert "Untitled div content" in result[0]["content"]
        assert result[1]["title"] == "Parent - Titled"
