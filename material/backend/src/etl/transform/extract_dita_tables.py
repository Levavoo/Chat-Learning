"""Extract <table> blocks from DITA XML as standalone PipelineItems.

Tables in DRV brochures are lookup units — Pflegegrade, Beitragssätze,
Überleitungstabellen. Indexing them as their own chunks gives BM25 and
embedding retrieval a focused target for "was bedeutet X?" / "wie hoch
ist Y?" queries, and prevents the overlap-splitter from slicing a table
mid-row when the enclosing H2 section exceeds the chunk threshold.
"""

import copy
import xml.etree.ElementTree as ET
from typing import ClassVar

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.base import Transform
from etl.util.logging_setup import get_logger


class extract_dita_tables(Transform):
    r"""Emit the original XML plus one wrapped XML item per <table>.

    Each table item is a minimal DITA topic whose body contains the
    immediately-preceding paragraph (lead-in sentence) and the table
    itself; section context becomes the topic title. It then passes
    through DITA2HTML → TEXT2MD → CHUNK_MARKDOWN and lands as a single
    chunk with chunk_type=table.

    input_types:
        XML
    output_type:
        XML
    name:
        \"EXTRACT_DITA_TABLES\"
    """

    output_type = DataType.XML
    supported_input_types: ClassVar[list[DataType]] = [DataType.XML]
    transform_type = "EXTRACT_DITA_TABLES"

    logger = get_logger("EXTRACT_DITA_TABLES")

    def apply(self, item: PipelineItem) -> list[PipelineItem]:
        data = item.data_object.data
        if isinstance(data, bytes):
            data = data.decode("UTF-8")
        elif not isinstance(data, str):
            raise TypeError(f"Expected str/bytes for XML data, got {type(data).__name__}")

        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            self.logger.warning("Failed to parse XML for table extraction; passing through")
            return [item]

        topic_title = self._element_text(root.find("title"))
        tables: list[dict] = []
        self._walk(root, section_title=topic_title, subsection_title="", tables=tables)

        result: list[PipelineItem] = [item]
        base_name = item.data_object.name
        used_titles: set[str] = set()

        for idx, table in enumerate(tables):
            preferred_title = self._preferred_title(table)
            document_title = self._unique_title(preferred_title, used_titles)
            table_xml = self._wrap_as_topic(table, document_title)
            table_metadata = copy.deepcopy(item.data_object.metadata)
            table_metadata["chunk_type"] = "table"
            if table["table_title"]:
                table_metadata["table_title"] = table["table_title"]
            if table["section_title"]:
                table_metadata["section_title"] = table["section_title"]
            if table["subsection_title"]:
                table_metadata["subsection_title"] = table["subsection_title"]

            table_name = f"{base_name}_table_{idx:03d}"
            result.append(
                PipelineItem(
                    name=table_name,
                    source_object=item.source_object,
                    data_object=DataObject(
                        name=table_name,
                        data=table_xml,
                        data_type=DataType.XML,
                        metadata=table_metadata,
                    ),
                )
            )

        self.logger.info(f"Extracted {len(tables)} table(s) from {base_name}")
        return result

    def _walk(
        self,
        element: ET.Element,
        section_title: str,
        subsection_title: str,
        tables: list[dict],
    ) -> None:
        current_subsection = subsection_title
        last_paragraph: ET.Element | None = None

        for child in element:
            tag = child.tag.lower()

            if tag == "section":
                child_section = self._element_text(child.find("title")) or section_title
                self._walk(child, section_title=child_section, subsection_title="", tables=tables)
                last_paragraph = None
            elif tag == "wintitle":
                current_subsection = self._element_text(child)
                last_paragraph = None
            elif tag == "p":
                last_paragraph = child
                self._walk(
                    child,
                    section_title=section_title,
                    subsection_title=current_subsection,
                    tables=tables,
                )
            elif tag == "table":
                title_text = self._element_text(child.find("title"))
                caption_text = self._caption_text(last_paragraph)
                tables.append({
                    "element": child,
                    "table_title": title_text,
                    "caption_title": caption_text,
                    "section_title": section_title,
                    "subsection_title": current_subsection,
                    "lead_in": last_paragraph,
                })
                last_paragraph = None
            elif tag in ("prolog", "metadata", "data"):
                continue
            else:
                self._walk(
                    child,
                    section_title=section_title,
                    subsection_title=current_subsection,
                    tables=tables,
                )

    @classmethod
    def _wrap_as_topic(cls, table: dict, title_text: str) -> str:
        topic = ET.Element("topic")
        title = ET.SubElement(topic, "title")
        title.text = title_text
        body = ET.SubElement(topic, "body")
        if table["lead_in"] is not None and not cls._same_title(cls._element_text(table["lead_in"]), title_text):
            body.append(copy.deepcopy(table["lead_in"]))

        table_element = copy.deepcopy(table["element"])
        table_caption = table_element.find("title")
        if table_caption is not None and cls._same_title(cls._element_text(table_caption), title_text):
            table_element.remove(table_caption)
        body.append(table_element)

        return ET.tostring(topic, encoding="unicode")

    @classmethod
    def _preferred_title(cls, table: dict) -> str:
        if table["table_title"]:
            return table["table_title"]
        if table["caption_title"]:
            return table["caption_title"].rstrip(":").strip()

        parts = [t for t in (table["section_title"], table["subsection_title"]) if t]
        return " – ".join(parts) if parts else "Tabelle"  # noqa: RUF001

    @classmethod
    def _unique_title(cls, preferred_title: str, used_titles: set[str]) -> str:
        candidate = preferred_title
        suffix = 2
        while cls._normalized_title(candidate) in used_titles:
            candidate = f"{preferred_title} – Tabelle {suffix}"  # noqa: RUF001
            suffix += 1
        used_titles.add(cls._normalized_title(candidate))
        return candidate

    @classmethod
    def _same_title(cls, left: str, right: str) -> bool:
        return cls._normalized_title(left) == cls._normalized_title(right)

    @staticmethod
    def _normalized_title(value: str) -> str:
        return " ".join(value.rstrip(":").split()).casefold()

    @classmethod
    def _caption_text(cls, paragraph: ET.Element | None) -> str:
        if paragraph is None or paragraph.get("otherprops") != "note-ueberschrift":
            return ""
        return cls._element_text(paragraph)

    @staticmethod
    def _element_text(el: ET.Element | None) -> str:
        if el is None:
            return ""
        return "".join(el.itertext()).strip()
