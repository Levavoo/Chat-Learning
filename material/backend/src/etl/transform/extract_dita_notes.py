"""Extract <note> blocks from DITA XML as standalone PipelineItems.

Notes in DRV brochures are author-curated "if you have this question, here's
the answer" units (Unser Tipp, Bitte beachten Sie). Indexing them as their
own chunks gives retrieval a high-density signal that is otherwise diluted
inside a 2500-char H2 chunk.
"""

import copy
import xml.etree.ElementTree as ET
from typing import ClassVar

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.base import Transform
from etl.util.logging_setup import get_logger

# Note `othertype` values worth indexing as standalone chunks.
# DRV brochures encode notes as <note type="other" othertype="..."> with German
# values: "wichtig" (author-flagged important) and "unbekannt" (uncategorised).
# Only "wichtig" is indexed — "unbekannt" is filler/uncategorised by definition.
_INDEXABLE_NOTE_TYPES = frozenset({"wichtig"})


class extract_dita_notes(Transform):
    r"""Emit the original XML plus one wrapped XML item per <note> block.

    Each note item is a minimal DITA topic carrying section context as its
    title; it then passes through DITA2HTML → TEXT2MD → CHUNK_MARKDOWN like
    any other XML and lands as a single chunk with chunk_type=note.

    input_types:
        XML
    output_type:
        XML
    name:
        \"EXTRACT_DITA_NOTES\"
    """

    output_type = DataType.XML
    supported_input_types: ClassVar[list[DataType]] = [DataType.XML]
    transform_type = "EXTRACT_DITA_NOTES"

    logger = get_logger("EXTRACT_DITA_NOTES")

    def apply(self, item: PipelineItem) -> list[PipelineItem]:
        data = item.data_object.data
        if isinstance(data, bytes):
            data = data.decode("UTF-8")
        elif not isinstance(data, str):
            raise TypeError(f"Expected str/bytes for XML data, got {type(data).__name__}")

        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            self.logger.warning("Failed to parse XML for note extraction; passing through")
            return [item]

        topic_title = self._element_text(root.find("title"))
        notes: list[dict] = []
        self._walk(root, section_title=topic_title, subsection_title="", notes=notes)

        result: list[PipelineItem] = [item]
        base_name = item.data_object.name

        for idx, note in enumerate(notes):
            note_xml = self._wrap_as_topic(note)
            note_metadata = copy.deepcopy(item.data_object.metadata)
            note_metadata["chunk_type"] = "note"
            note_metadata["note_type"] = note["note_type"]
            if note["section_title"]:
                note_metadata["section_title"] = note["section_title"]
            if note["subsection_title"]:
                note_metadata["subsection_title"] = note["subsection_title"]

            note_name = f"{base_name}_note_{idx:03d}"
            result.append(
                PipelineItem(
                    name=note_name,
                    source_object=item.source_object,
                    data_object=DataObject(
                        name=note_name,
                        data=note_xml,
                        data_type=DataType.XML,
                        metadata=note_metadata,
                    ),
                )
            )

        self.logger.info(f"Extracted {len(notes)} indexable note(s) from {base_name}")
        return result

    def _walk(
        self,
        element: ET.Element,
        section_title: str,
        subsection_title: str,
        notes: list[dict],
    ) -> None:
        current_subsection = subsection_title

        for child in element:
            tag = child.tag.lower()

            if tag == "section":
                child_section = self._element_text(child.find("title")) or section_title
                self._walk(child, section_title=child_section, subsection_title="", notes=notes)
            elif tag == "wintitle":
                current_subsection = self._element_text(child)
            elif tag == "note":
                note_type = self._resolve_note_type(child)
                if note_type in _INDEXABLE_NOTE_TYPES:
                    notes.append({
                        "element": child,
                        "note_type": note_type,
                        "section_title": section_title,
                        "subsection_title": current_subsection,
                    })
            elif tag in ("prolog", "metadata", "data"):
                continue
            else:
                self._walk(
                    child,
                    section_title=section_title,
                    subsection_title=current_subsection,
                    notes=notes,
                )

    @staticmethod
    def _resolve_note_type(note_el: ET.Element) -> str:
        other = (note_el.get("othertype") or "").strip()
        if other:
            return other
        return (note_el.get("type") or "note").strip()

    @staticmethod
    def _wrap_as_topic(note: dict) -> str:
        parts = [t for t in (note["section_title"], note["subsection_title"]) if t]
        title_text = " – ".join(parts) if parts else "Hinweis"  # noqa: RUF001

        topic = ET.Element("topic")
        title = ET.SubElement(topic, "title")
        title.text = title_text
        body = ET.SubElement(topic, "body")
        # Deep-copy so we don't mutate the source tree.
        body.append(copy.deepcopy(note["element"]))

        return ET.tostring(topic, encoding="unicode")

    @staticmethod
    def _element_text(el: ET.Element | None) -> str:
        if el is None:
            return ""
        return "".join(el.itertext()).strip()
