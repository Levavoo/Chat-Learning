"""Custom chunking logic for DITA-based brochures."""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt

from etl.util.chunking.text_splitter import split_text_with_overlap

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """Represents a single chunk of text with metadata."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def extract_dita_metadata(xml_content: str) -> dict[str, Any]:
    """Placeholder for DITA ``<prolog>`` metadata extraction."""
    return {}


class CustomChunker:
    """Chunks Markdown documents based on their semantic structure."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.min_divs_for_hierarchical = self.config.get("minDivsForHierarchical", 3)
        self.flat_section_split_threshold = self.config.get("flatSectionSplitThreshold", 2500)
        self.flat_section_overlap = self.config.get("flatSectionOverlap", 300)
        self.md_parser = MarkdownIt()

    def chunk(self, markdown: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Chunk the input markdown based on the strategy."""
        brochure_number = metadata.get("brochure_number", "")

        # B28 / B37 are glossary documents; B38 is flat.
        if brochure_number in ["B28", "B37"]:
            return self._chunk_glossary_entries(markdown, metadata)
        elif brochure_number == "B38":
            return self._chunk_flat_sections(markdown, metadata)
        elif self._has_hierarchical_divs(markdown):
            return self._chunk_hierarchical_divs(markdown, metadata)
        else:
            logger.warning(f"No specific strategy match for {brochure_number}. Using Flat Section fallback.")
            return self._chunk_flat_sections(markdown, metadata)

    def _has_hierarchical_divs(self, markdown: str) -> bool:
        """Detect hierarchical pattern (enough H3 headers from divs)."""
        h3_count = markdown.count("\n### ")
        return h3_count >= self.min_divs_for_hierarchical

    def _extract_sections(self, markdown: str, level: int = 2) -> list[Chunk]:
        """Extract sections at the given header level (keeping the heading in the chunk)."""
        pattern = re.compile(f"^{'#' * level} (.+)$", re.MULTILINE)
        matches = list(pattern.finditer(markdown))

        sections = []
        for i, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
            content = markdown[start:end].strip()
            sections.append(Chunk(content=content, metadata={"title": title}))

        return sections

    def _chunk_hierarchical_divs(self, markdown: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Chunk at H3 level, preserving H2 context."""
        chunks = []
        h2_sections = self._extract_sections(markdown, level=2)

        for section in h2_sections:
            section_title = section.metadata["title"]
            h3_divs = self._extract_sections(section.content, level=3)

            if not h3_divs:
                chunk = Chunk(content=section.content, metadata=metadata.copy())
                chunk.metadata.update({
                    "chunk_type": "section_intro",
                    "section_title": section_title,
                })
                chunks.append(chunk)
                continue

            for div_index, div in enumerate(h3_divs):
                chunk = Chunk(content=div.content, metadata=metadata.copy())
                chunk.metadata.update({
                    "chunk_type": "hierarchical_div",
                    "section_title": section_title,
                    "subsection_title": div.metadata["title"],
                    "div_index": div_index,
                })
                self._enrich_metadata(chunk)
                chunks.append(chunk)

        return chunks

    def _chunk_glossary_entries(self, markdown: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Chunk glossary entries into (term + definition) pairs."""
        chunks = []
        paragraphs = markdown.split("\n\n")

        i = 0
        while i < len(paragraphs):
            para = paragraphs[i].strip()
            if not para:
                i += 1
                continue

            if para.startswith("#"):
                i += 1
                continue

            if self._is_glossary_term(para):
                term = para
                definition_paras = []
                i += 1

                while (
                    i < len(paragraphs)
                    and not self._is_glossary_term(paragraphs[i])
                    and not paragraphs[i].startswith("#")
                ):
                    definition_paras.append(paragraphs[i])
                    i += 1

                if definition_paras:
                    full_content = f"**{term}**\n\n" + "\n\n".join(definition_paras)
                    chunk = Chunk(content=full_content, metadata=metadata.copy())
                    chunk.metadata.update({
                        "chunk_type": "glossary_entry",
                        "glossary_term": term,
                        "term_category": "general",
                        "xref_count": full_content.count("["),
                    })
                    self._enrich_metadata(chunk)
                    chunks.append(chunk)
            else:
                i += 1

        return chunks

    def _is_glossary_term(self, text: str) -> bool:
        """Heuristic: short (< 80 chars) and no end punctuation."""
        clean = text.strip()
        if len(clean) > 80:
            return False
        return not (clean.endswith(".") or clean.endswith(":"))

    def _chunk_flat_sections(self, markdown: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Chunk flat sections, splitting large ones with overlap."""
        chunks = []
        sections = self._extract_sections(markdown, level=2)

        if not sections:
            return [Chunk(content=markdown, metadata=metadata)]

        for section in sections:
            if len(section.content) > self.flat_section_split_threshold:
                sub_chunks = split_text_with_overlap(
                    section.content, self.flat_section_split_threshold, self.flat_section_overlap
                )
                for sub in sub_chunks:
                    chunk = Chunk(content=sub, metadata=metadata.copy())
                    chunk.metadata.update({
                        "chunk_type": "flat_section_split",
                        "section_title": section.metadata["title"],
                    })
                    self._enrich_metadata(chunk)
                    chunks.append(chunk)
            else:
                chunk = Chunk(content=section.content, metadata=metadata.copy())
                chunk.metadata.update({"chunk_type": "flat_section", "section_title": section.metadata["title"]})
                self._enrich_metadata(chunk)
                chunks.append(chunk)

        return chunks

    def _enrich_metadata(self, chunk: Chunk) -> None:
        """Add content-based metadata to chunk (in place)."""
        content = chunk.content
        chunk.metadata["has_table"] = "|---" in content or "| ---" in content
        chunk.metadata["has_note"] = "**Unser Tipp**" in content or "**Bitte beachten Sie**" in content

        note_types: list[str] = []
        if "**Unser Tipp**" in content:
            note_types.append("tip")
        if "**Bitte beachten Sie**" in content:
            note_types.append("important")
        if note_types:
            chunk.metadata["note_types"] = note_types
