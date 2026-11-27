"""Hierarchical H2-level chunking strategy."""

import re
from typing import Any

from etl.util.chunking.base import Chunk, ChunkingStrategy
from etl.util.chunking.text_splitter import split_section_preserving_tables


class HierarchicalChunkingStrategy(ChunkingStrategy):
    """Chunks documents at H2 level, splitting oversized sections with overlap."""

    def __init__(
        self,
        section_split_threshold: int = 2500,
        section_overlap: int = 300,
    ):
        self.section_split_threshold = section_split_threshold
        self.section_overlap = section_overlap

    def chunk(self, text: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Chunk hierarchical markdown content by H2 sections."""
        chunks = []
        h2_sections = self._extract_sections(text, level=2)

        for section in h2_sections:
            section_title = section.metadata["title"]

            if len(section.content) > self.section_split_threshold:
                sub_chunks = split_section_preserving_tables(
                    section.content,
                    self.section_split_threshold,
                    self.section_overlap,
                )
                for sub in sub_chunks:
                    # A chunk beginning with "\n(" is misdetected by Bedrock's
                    # content-type sniffer (Apache Tika) as an unsupported binary
                    # format and silently dropped at ingestion.
                    sub = sub.strip()
                    if not sub:
                        continue
                    chunk = Chunk(content=sub, metadata=metadata.copy())
                    chunk.metadata.update({
                        "chunk_type": "hierarchical_section_split",
                        "section_title": section_title,
                    })
                    self._enrich_metadata(chunk)
                    chunks.append(chunk)
            else:
                chunk = Chunk(content=section.content, metadata=metadata.copy())
                chunk.metadata.update({
                    "chunk_type": "hierarchical_section",
                    "section_title": section_title,
                })
                self._enrich_metadata(chunk)
                chunks.append(chunk)

        return chunks

    def _extract_sections(self, text: str, level: int = 2) -> list[Chunk]:
        """Extract sections based on header level."""
        pattern = re.compile(f"^{'#' * level} (.+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))

        sections = []
        for i, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()

            sections.append(Chunk(content=content, metadata={"title": title}))

        return sections

    def _enrich_metadata(self, chunk: Chunk) -> None:
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
