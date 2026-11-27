import logging
import xml.etree.ElementTree as ET
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field

from etl.util.parsing.base import BaseParser

logger = logging.getLogger(__name__)


class DitaNodeType(StrEnum):
    TOPIC = "topic"
    SECTION = "section"
    BODY = "body"
    BODY_DIV = "body_div"
    SECTION_DIV = "section_div"
    PARAGRAPH = "paragraph"
    SUBHEADING = "subheading"
    ORDERED_LIST = "ordered_list"
    UNORDERED_LIST = "unordered_list"
    LIST_ITEM = "list_item"
    TABLE = "table"
    TABLE_GROUP = "table_group"
    TABLE_ROW = "table_row"
    TABLE_ENTRY = "table_entry"
    CODEBLOCK = "codeblock"
    NOTE = "note"
    TEXT = "text"
    BOLD = "bold"
    ITALIC = "italic"
    EMPHASIS = "emphasis"
    STRONG = "strong"
    UNDERLINE = "underline"
    CODE = "code"
    SUBSCRIPT = "subscript"
    SUPERSCRIPT = "superscript"
    PHRASE = "phrase"
    TELETYPE = "teletype"
    KEYWORD = "keyword"
    WINTITLE = "wintitle"
    XREF = "xref"
    FOOTNOTE = "footnote"
    TITLE = "title"
    UNKNOWN = "unknown"


class DitaMetadata(BaseModel):
    title: str | None = None
    category: str | None = None
    keywords: list[str] = Field(default_factory=list)
    custom_data: dict[str, str] = Field(default_factory=dict)


class DitaNode(BaseModel):
    node_type: DitaNodeType
    text: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    children: list["DitaNode"] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "node_type": self.node_type.value,
            "text": self.text,
            "attributes": self.attributes,
            "children": [child.to_dict() for child in self.children],
        }


class DitaDocument(BaseModel):
    metadata: DitaMetadata = Field(default_factory=DitaMetadata)
    content: DitaNode | None = None
    node_dict: dict[str, DitaNode] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "metadata": self.metadata.model_dump(),
            "content": self.content.to_dict() if self.content else None,
        }


class DitaParser(BaseParser):
    """Parses DITA XML into structured document representation."""

    _TAG_ALIASES: ClassVar[dict[str, str]] = {
        "p": "paragraph",
        "ol": "ordered_list",
        "ul": "unordered_list",
        "li": "list_item",
        "tgroup": "table_group",
        "row": "table_row",
        "entry": "table_entry",
        "b": "bold",
        "i": "italic",
        "em": "emphasis",
        "u": "underline",
        "fn": "footnote",
        "bodydiv": "body_div",
        "sectiondiv": "section_div",
        "sub": "subscript",
        "sup": "superscript",
        "ph": "phrase",
        "tt": "teletype",
    }

    INLINE_TAGS: ClassVar[set[str]] = {
        "b",
        "i",
        "em",
        "strong",
        "u",
        "code",
        "keyword",
        "wintitle",
        "xref",
        "fn",
        "sub",
        "sup",
        "ph",
        "tt",
    }

    SKIP_TAGS: ClassVar[set[str]] = {"prolog", "metadata", "data", "change-historylist"}

    SUBHEADING_OTHERPROPS: ClassVar[str] = "zwischenueberschrift"

    # Punctuation that legitimately closes the clause a footnote was attached to.
    # A footnote tail starting with one of these continues the sentence, so no
    # separator is inserted -- ").)" and ") ." would both be wrong.
    FOOTNOTE_TAIL_NO_SPACE: ClassVar[str] = ".,;:!?)]}»“”"

    # Per-tag attributes to preserve on the parsed node. CALS geometry
    # attributes on <entry> (colname, namest, nameend, morerows) are required
    # to rebuild a rectangular table. Column order itself comes from the
    # <colspec> elements, read directly from the XML in _parse_tgroup.
    _PRESERVED_ATTRS: ClassVar[dict[str, tuple[str, ...]]] = {
        "xref": ("href", "scope"),
        "note": ("type", "othertype"),
        "entry": ("colname", "namest", "nameend", "morerows"),
    }

    def _resolve_node_type(self, tag: str) -> DitaNodeType:
        node_type_value = self._TAG_ALIASES.get(tag, tag)
        try:
            return DitaNodeType(node_type_value)
        except ValueError:
            return DitaNodeType.UNKNOWN

    def parse(self, data: str) -> dict:
        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            logger.exception("Failed to parse DITA XML")
            raise ValueError(f"Invalid XML content: {e}") from e

        document = self._parse_document(root)
        return document.to_dict()

    def parse_to_model(self, data: str) -> DitaDocument:
        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            logger.exception("Failed to parse DITA XML")
            raise ValueError(f"Invalid XML content: {e}") from e

        return self._parse_document(root)

    def _build_node_dict(self, node: DitaNode) -> dict[str, DitaNode]:
        node_dict = {}
        node_id = node.attributes.get("id")
        if node_id:
            node_dict[node_id] = node

        for child in node.children:
            node_dict.update(self._build_node_dict(child))

        return node_dict

    def _parse_document(self, root: ET.Element) -> DitaDocument:
        metadata = self._extract_metadata(root)
        content = self._parse_element(root)
        node_dict = self._build_node_dict(content)
        return DitaDocument(metadata=metadata, content=content, node_dict=node_dict)

    def _extract_metadata(self, root: ET.Element) -> DitaMetadata:
        metadata = DitaMetadata()

        # Extract title
        title_el = root.find("title")
        if title_el is not None:
            metadata.title = self._get_full_text(title_el).strip() or None

        # Extract prolog metadata
        prolog = root.find("prolog")
        if prolog is None:
            return metadata

        # Extract data elements
        for data_el in prolog.findall("data"):
            name = data_el.get("name")
            value = data_el.get("value")
            if name and value:
                metadata.custom_data[name] = value

        # Extract metadata element contents
        meta_el = prolog.find("metadata")
        if meta_el is not None:
            self._extract_metadata_element(meta_el, metadata)

        return metadata

    def _extract_metadata_element(self, meta_el: ET.Element, metadata: DitaMetadata) -> None:
        category = meta_el.find("category")
        if category is not None and category.text:
            metadata.category = category.text.strip()

        keywords_el = meta_el.find("keywords")
        if keywords_el is not None:
            for kw in keywords_el.findall("keyword"):
                if kw.text:
                    metadata.keywords.append(kw.text.strip())

        for othermeta in meta_el.findall("othermeta"):
            name = othermeta.get("name")
            content = othermeta.get("content")
            if name and content:
                metadata.custom_data[name] = content

    _tag_handlers: ClassVar[dict[str, str]] = {
        "topic": "_parse_topic",
        "section": "_parse_section",
        "sectiondiv": "_parse_section_div",
        "bodydiv": "_parse_section_div",
        "ol": "_parse_list",
        "ul": "_parse_list",
        "table": "_parse_table",
        "tgroup": "_parse_tgroup",
        "thead": "_parse_table_section",
        "tbody": "_parse_table_section",
        "row": "_parse_row",
        "p": "_parse_paragraph",
        "li": "_parse_mixed_content",
        "entry": "_parse_mixed_content",
        "codeblock": "_parse_codeblock",
        "note": "_parse_note",
        "title": "_parse_title",
        "body": "_parse_container",
    }

    def _parse_element(self, el: ET.Element) -> DitaNode:
        tag = el.tag.lower()
        node_type = self._resolve_node_type(tag)
        attributes = self._extract_attributes(el, tag)

        if tag in self._tag_handlers:
            handler = getattr(self, self._tag_handlers[tag])
            return handler(el, node_type, attributes)

        if tag in self.INLINE_TAGS:
            return self._parse_inline_element(el, node_type, attributes)

        return self._parse_container(el, node_type, attributes)

    def _extract_attributes(self, el: ET.Element, tag: str) -> dict[str, str]:
        attributes = {}

        if "id" in el.attrib:
            attributes["id"] = el.attrib["id"]

        for attr in self._PRESERVED_ATTRS.get(tag, ()):
            if attr in el.attrib:
                attributes[attr] = el.attrib[attr]

        # otherprops carries semantic role (subheading, vorwort, hauptstichwort) —
        # preserve so renderers can promote subheadings to <h3>.
        if "otherprops" in el.attrib:
            attributes["otherprops"] = el.attrib["otherprops"]

        return attributes

    def _parse_topic(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        children = []

        title_el = el.find("title")
        if title_el is not None:
            children.append(self._parse_element(title_el))

        for child in el:
            if child.tag.lower() not in ("title", "prolog", "metadata"):
                children.append(self._parse_element(child))

        return DitaNode(node_type=node_type, attributes=attributes, children=children)

    def _parse_section(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        children = []

        title_el = el.find("title")
        if title_el is not None:
            children.append(self._parse_element(title_el))

        for child in el:
            if child.tag.lower() != "title":
                children.append(self._parse_element(child))

        return DitaNode(node_type=node_type, attributes=attributes, children=children)

    def _parse_section_div(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        # <sectiondiv>/<bodydiv>: section-like containers from the 2026+ export.
        children = []

        title_el = el.find("title")
        if title_el is not None:
            children.append(self._parse_element(title_el))

        for child in el:
            if child.tag.lower() != "title":
                children.append(self._parse_element(child))

        return DitaNode(node_type=node_type, attributes=attributes, children=children)

    def _parse_paragraph(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        # 2026+ export emits subsection headings as <p otherprops="zwischenueberschrift">
        # instead of <wintitle>; retag so HTML can emit <h3> for custom_chunking.
        if attributes.get("otherprops") == self.SUBHEADING_OTHERPROPS:
            node_type = DitaNodeType.SUBHEADING
        return self._parse_mixed_content(el, node_type, attributes)

    def _parse_list(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        children = []
        for li in el.findall("li"):
            children.append(self._parse_element(li))
        return DitaNode(node_type=node_type, attributes=attributes, children=children)

    def _collect_children(self, el: ET.Element) -> list[DitaNode]:
        children = []
        text = self._clean_text(el.text)
        if text:
            children.append(DitaNode(node_type=DitaNodeType.TEXT, text=text))

        for child in el:
            tag = child.tag.lower()
            if tag in self.SKIP_TAGS:
                tail = self._clean_text(child.tail)
                if tail:
                    children.append(DitaNode(node_type=DitaNodeType.TEXT, text=tail))
                continue

            parsed = self._parse_element(child)
            children.append(parsed)

            tail = self._clean_text(child.tail)
            if tail:
                children.append(DitaNode(node_type=DitaNodeType.TEXT, text=self._separate_tail(parsed, tail)))

        return children

    @staticmethod
    def _clean_text(text: str | None) -> str:
        # Drop U+FEFF filler used in empty layout cells; left in place it ends up
        # inside merged table-header labels and breaks exact matching.
        return (text or "").replace("\ufeff", "")

    @classmethod
    def _separate_tail(cls, previous: DitaNode, tail: str) -> str:
        # DRV brochures put <fn outputclass="sidenote"> at the head of a <p>,
        # so the paragraph's prose is the footnote's tail; keep them from fusing
        # into one token for the embedder.
        if previous.node_type != DitaNodeType.FOOTNOTE:
            return tail
        if not tail or tail[0].isspace() or tail[0] in cls.FOOTNOTE_TAIL_NO_SPACE:
            return tail
        return " " + tail

    def _parse_mixed_content(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        children = self._collect_children(el)
        if len(children) == 1 and children[0].node_type == DitaNodeType.TEXT:
            return DitaNode(
                node_type=node_type,
                text=children[0].text,
                attributes=attributes,
            )

        return DitaNode(node_type=node_type, attributes=attributes, children=children)

    def _parse_table(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        children = []
        for child in el:
            children.append(self._parse_element(child))
        return DitaNode(node_type=node_type, attributes=attributes, children=children)

    def _parse_tgroup(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        # Column order (from <colspec>) + declared count so the renderer maps
        # colname/namest/nameend to grid positions.
        colnames = [cs.get("colname", "") for cs in el.findall("colspec") if cs.get("colname")]
        if colnames:
            attributes["colnames"] = ",".join(colnames)
        if el.get("cols"):
            attributes["cols"] = el.get("cols", "")

        children = []
        for child in el:
            children.append(self._parse_element(child))
        return DitaNode(node_type=node_type, attributes=attributes, children=children)

    def _parse_table_section(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        # Preserve whether this is the header (<thead>) or body (<tbody>); both
        # otherwise parse to TABLE_GROUP and the distinction is needed to build
        # the header row(s).
        attributes = {**attributes, "table_section": el.tag.lower()}
        children = []
        for row in el.findall("row"):
            children.append(self._parse_element(row))
        return DitaNode(node_type=DitaNodeType.TABLE_GROUP, attributes=attributes, children=children)

    def _parse_row(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        children = []
        for entry in el.findall("entry"):
            children.append(self._parse_element(entry))
        return DitaNode(node_type=node_type, attributes=attributes, children=children)

    def _parse_codeblock(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        text = self._get_text(el)
        return DitaNode(node_type=node_type, text=text, attributes=attributes)

    def _parse_note(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        if "type" not in attributes:
            attributes["type"] = el.get("type", "note")

        children = []
        for child in el:
            children.append(self._parse_element(child))

        return DitaNode(node_type=node_type, attributes=attributes, children=children)

    def _parse_container(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        children = []
        for child in el:
            if child.tag.lower() not in self.SKIP_TAGS:
                children.append(self._parse_element(child))
        return DitaNode(node_type=node_type, attributes=attributes, children=children)

    def _parse_title(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        text = self._get_full_text(el).strip()
        return DitaNode(node_type=node_type, text=text, attributes=attributes)

    def _parse_inline_element(self, el: ET.Element, node_type: DitaNodeType, attributes: dict[str, str]) -> DitaNode:
        children = self._collect_children(el)
        if len(children) == 1 and children[0].node_type == DitaNodeType.TEXT:
            return DitaNode(
                node_type=node_type,
                text=children[0].text,
                attributes=attributes,
            )

        if not children:
            return DitaNode(node_type=node_type, attributes=attributes)

        return DitaNode(node_type=node_type, attributes=attributes, children=children)

    def _get_text(self, el: ET.Element) -> str:
        return (el.text or "").strip()

    def _get_full_text(self, el: ET.Element) -> str:
        text = el.text or ""
        for child in el:
            text += self._get_full_text(child)
            if child.tail:
                text += child.tail
        return text.strip()
