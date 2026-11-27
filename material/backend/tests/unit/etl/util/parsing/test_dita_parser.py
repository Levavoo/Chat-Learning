import pytest

from etl.util.parsing.dita import DitaParser

SAMPLE_DITA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<topic id="b01">
  <title>Test Brochure Title</title>
  <prolog>
    <metadata>
      <category>Rehabilitation</category>
      <keywords>
        <keyword>Keyword1</keyword>
        <keyword>Keyword2</keyword>
      </keywords>
    </metadata>
    <data name="filename" value="Test File Name"/>
    <data name="broschrennummer" value="B01"/>
    <data name="veroeffentlichung" value="9/2024"/>
    <data name="auflage" value="19. Auflage"/>
  </prolog>
  <body>
    <section>
      <title>Section 1 Title</title>
      <p>Paragraph 1 text.</p>
    </section>
    <div>
        <wintitle>Subsection Title</wintitle>
        <p>Subsection paragraph.</p>
        <ul>
            <li>List item 1</li>
            <li>List item 2</li>
        </ul>
        <note type="tip">
            <p>This is a tip.</p>
        </note>
    </div>
  </body>
</topic>
"""


@pytest.fixture
def parser():
    return DitaParser()


def test_extract_metadata(parser):
    result = parser.parse(SAMPLE_DITA_XML)
    metadata = result["metadata"]

    assert metadata["title"] == "Test Brochure Title"
    assert metadata["custom_data"]["broschrennummer"] == "B01"
    assert metadata["custom_data"]["veroeffentlichung"] == "9/2024"
    assert metadata["custom_data"]["auflage"] == "19. Auflage"
    assert metadata["custom_data"]["filename"] == "Test File Name"
    assert metadata["category"] == "Rehabilitation"
    assert "Keyword1" in metadata["keywords"]
    assert "Keyword2" in metadata["keywords"]


def test_parse_content_structure(parser):
    result = parser.parse(SAMPLE_DITA_XML)
    content = result["content"]

    assert content["node_type"] == "topic"

    title_node = content["children"][0]
    assert title_node["node_type"] == "title"
    assert title_node["text"] == "Test Brochure Title"

    body_node = content["children"][1]
    assert body_node["node_type"] == "body"


def test_parse_section(parser):
    result = parser.parse(SAMPLE_DITA_XML)
    body_node = result["content"]["children"][1]  # body

    section_node = body_node["children"][0]
    assert section_node["node_type"] == "section"

    section_title = section_node["children"][0]
    assert section_title["node_type"] == "title"
    assert section_title["text"] == "Section 1 Title"

    section_para = section_node["children"][1]
    assert section_para["node_type"] == "paragraph"


def test_parse_list(parser):
    result = parser.parse(SAMPLE_DITA_XML)
    body_node = result["content"]["children"][1]  # body

    div_node = body_node["children"][1]
    list_node = next(c for c in div_node["children"] if c["node_type"] == "unordered_list")

    assert list_node["node_type"] == "unordered_list"
    assert len(list_node["children"]) == 2

    li1 = list_node["children"][0]
    assert li1["node_type"] == "list_item"
    assert li1["text"] == "List item 1"


def test_parse_note(parser):
    result = parser.parse(SAMPLE_DITA_XML)
    body_node = result["content"]["children"][1]  # body

    div_node = body_node["children"][1]
    note_node = next(c for c in div_node["children"] if c["node_type"] == "note")

    assert note_node["node_type"] == "note"
    assert note_node["attributes"]["type"] == "tip"

    note_para = note_node["children"][0]
    assert note_para["node_type"] == "paragraph"


def test_parse_invalid_xml(parser):
    with pytest.raises(ValueError):
        parser.parse("<invalid>XML")


def _all_text(node: dict) -> str:
    return node["text"] + "".join(_all_text(child) for child in node["children"])


# DRV brochures place <fn outputclass="sidenote"> at the head of a <p>, so the
# paragraph's own prose arrives as the footnote's tail. Without a separator the
# rendered HTML reads "...alle Fälle".)Rentenbeginn vor dem..." -- one token.
@pytest.mark.parametrize(
    ("tail", "expected"),
    [
        ("Rentenbeginn vor dem 1. Januar 2012", " Rentenbeginn vor dem 1. Januar 2012"),
        ("Änderung ab 2024", " Änderung ab 2024"),
        ("„Fragebogen zur Zahlung“ folgt", " „Fragebogen zur Zahlung“ folgt"),
        (". Danach geht es weiter", ". Danach geht es weiter"),
        (", danach geht es weiter", ", danach geht es weiter"),
        (" bereits getrennt", " bereits getrennt"),
    ],
)
def test_footnote_tail_separator(parser, tail, expected):
    xml = f'<topic id="t"><body><p>Vorher<fn><ph>Hinweistext</ph></fn>{tail}</p></body></topic>'
    result = parser.parse(xml)

    paragraph = result["content"]["children"][0]["children"][0]
    tail_node = paragraph["children"][-1]

    assert tail_node["node_type"] == "text"
    assert tail_node["text"] == expected


def test_non_footnote_tail_is_untouched(parser):
    xml = '<topic id="t"><body><p>Sie können sich <b>als Paar </b>gemeinsam bewerben.</p></body></topic>'
    result = parser.parse(xml)

    paragraph = result["content"]["children"][0]["children"][0]

    assert _all_text(paragraph) == "Sie können sich als Paar gemeinsam bewerben."


def test_zero_width_no_break_space_is_stripped(parser):
    xml = '<topic id="t"><body><p><b>Beginn der Rente</b></p><p><b>&#xFEFF;</b></p></body></topic>'
    result = parser.parse(xml)

    assert "\ufeff" not in _all_text(result["content"])
