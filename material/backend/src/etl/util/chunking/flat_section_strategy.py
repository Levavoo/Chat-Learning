"""Flat section chunking strategy."""

import re
from typing import Any

from etl.util.chunking.base import Chunk, ChunkingStrategy
from etl.util.chunking.sentence_boundaries import pack_by_sentences
from etl.util.chunking.table_blocks import (
    find_table_spans,
    is_single_table_block,
    split_table_block,
)
from etl.util.chunking.text_splitter import (
    advance_past_partial_token,
    is_heading_like_line,
    is_list_line,
    split_section_preserving_tables,
)
from etl.util.logging_setup import get_logger

logger = get_logger("FLAT_SECTION_CHUNKING")


class FlatSectionChunkingStrategy(ChunkingStrategy):
    """Chunks flat documents by sections, splitting large ones with overlap."""

    # Fallback used only when a document has no H2 *and* no H3 headers.
    # Targets ~1k tokens per chunk, well under the 50k contextual-grounding ceiling.
    FALLBACK_CHUNK_TARGET = 3_000
    FALLBACK_OVERLAP = 300  # ~11% - within 10-20% best practice

    def __init__(
        self,
        section_split_threshold: int = 2500,
        section_overlap: int = 300,
        fallback_chunk_target: int | None = None,
        fallback_overlap: int | None = None,
        enable_headerless_fallback: bool = False,
    ):
        self.section_split_threshold = section_split_threshold
        self.section_overlap = section_overlap
        # Opt-in (default off) so the chunker stays format-agnostic. The H3-split,
        # preamble, and paragraph-clustering fallbacks below only fire when this
        # is enabled — currently only for PDFs. XML keeps the historical
        # "headerless doc -> single chunk" behaviour regardless of its structure.
        self.enable_headerless_fallback = enable_headerless_fallback
        self.fallback_chunk_target = (
            fallback_chunk_target if fallback_chunk_target is not None else self.FALLBACK_CHUNK_TARGET
        )
        self.fallback_overlap = fallback_overlap if fallback_overlap is not None else self.FALLBACK_OVERLAP

    def chunk(self, text: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Chunk flat markdown content into sections.

        Routing:
          1. H2 headers present  -> split on H2 (primary behaviour).
          2. No H2 headers       -> if ``enable_headerless_fallback`` (PDF only),
             split on H3 preserving any preamble, then paragraph-cluster a large
             headerless body. Otherwise keep the whole document as one chunk.
        """
        chunks = []
        sections = self._extract_sections(text, level=2)

        if not sections and self.enable_headerless_fallback:
            sections, preamble = self._extract_sections_with_preamble(text, level=3)
            if preamble:
                # Route the preamble through the splitting path: a large preamble
                # before a trailing H3 must not become one oversized chunk.
                chunks.extend(self._chunk_preamble(preamble, metadata))

        if not sections:
            # Split as soon as a headerless document exceeds the fallback target
            # (~1k tokens), not the 50k contextual-grounding ceiling: 50k-char
            # chunks would bump that ceiling, while ~1k tokens stays comfortably
            # retrievable.
            if self.enable_headerless_fallback and len(text) > self.fallback_chunk_target:
                return chunks + self._chunk_by_paragraphs(text, metadata)
            return [*chunks, *self._emit_headerless(text, metadata)]

        for section in sections:
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
                        "chunk_type": "flat_section_split",
                        "section_title": section_title,
                    })
                    self._enrich_metadata(chunk)
                    chunks.append(chunk)
            else:
                chunk = Chunk(content=section.content, metadata=metadata.copy())
                chunk.metadata.update({
                    "chunk_type": "flat_section",
                    "section_title": section_title,
                })
                self._enrich_metadata(chunk)
                chunks.append(chunk)

        return chunks

    def _emit_headerless(self, text: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Emit a headerless document as one chunk, splitting only oversized tables.

        Because the KB uses ``chunkingStrategy=NONE``, an oversized single chunk
        is truncated at the embedding token limit and tail rows are lost (#697).
        Any table span longer than ``section_split_threshold`` is continued with
        a repeated header/separator via ``split_table_block``; the preceding head
        (title + lead-in) stays on the first piece and any trailing text on the
        last. A table-free document returns exactly one chunk.
        """
        oversized = [(s, e) for s, e in find_table_spans(text) if e - s > self.section_split_threshold]
        if not oversized:
            return [Chunk(content=text, metadata=metadata)]

        pieces: list[str] = []
        cursor = 0
        for start, end in oversized:
            table_pieces = split_table_block(text[start:end], self.section_split_threshold)
            head = text[cursor:start]
            if head.strip():
                table_pieces[0] = f"{head.rstrip()}\n\n{table_pieces[0]}"
            pieces.extend(table_pieces)
            cursor = end

        trailing = text[cursor:]
        if trailing.strip():
            pieces[-1] = f"{pieces[-1]}\n\n{trailing.strip()}"

        result: list[Chunk] = []
        for index, piece in enumerate(pieces):
            chunk = Chunk(content=piece, metadata=metadata.copy())
            if index > 0:
                chunk.metadata["table_continuation"] = True
            result.append(chunk)
        return result

    def _extract_sections(self, text: str, level: int = 2) -> list[Chunk]:
        """Extract sections based on header level (any preamble is discarded)."""
        sections, _ = self._extract_sections_with_preamble(text, level)
        return sections

    def _chunk_preamble(self, preamble: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Emit the preamble (text before the first H3), split like a headerless body.

        A small preamble stays a single ``flat_section`` chunk; a large one is
        paragraph-clustered, each piece staying ``<= fallback_chunk_target``.
        """
        contents = self._cluster_paragraphs(preamble) if len(preamble) > self.fallback_chunk_target else [preamble]
        chunks: list[Chunk] = []
        for content in contents:
            chunk = Chunk(content=content, metadata=metadata.copy())
            chunk.metadata.update({
                "chunk_type": "flat_section",
                "section_title": "(preamble)",
            })
            self._enrich_metadata(chunk)
            chunks.append(chunk)
        return chunks

    def _extract_sections_with_preamble(self, text: str, level: int = 3) -> tuple[list[Chunk], str]:
        """Extract sections and return any preamble text before the first header.

        Returns:
            Tuple of (sections, preamble_text)

        """
        pattern = re.compile(f"^{'#' * level} (.+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))

        preamble = ""
        sections = []

        if matches:
            preamble = text[: matches[0].start()].strip()

            for i, match in enumerate(matches):
                title = match.group(1).strip()
                start = match.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                content = text[start:end].strip()
                sections.append(Chunk(content=content, metadata={"title": title}))

        return sections, preamble

    def _chunk_by_paragraphs(self, text: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Cluster paragraphs into ~``FALLBACK_CHUNK_TARGET``-sized chunks.

        Used for structureless documents (no H2/H3). Paragraphs are accumulated
        until adding the next would exceed the target; each emitted chunk seeds
        the next one with its trailing ``FALLBACK_OVERLAP`` characters so context
        is preserved across the boundary. Oversized paragraphs are split first.
        """
        section_title = metadata.get("name", "")
        chunks: list[Chunk] = []
        for content in self._cluster_paragraphs(text):
            chunk = Chunk(content=content, metadata=metadata.copy())
            chunk.metadata.update({
                "chunk_type": "flat_paragraph_fallback",
                "section_title": section_title,
            })
            self._enrich_metadata(chunk)
            chunks.append(chunk)

        logger.info(
            "No H2/H3 headers in %d-char document; paragraph fallback produced %d chunks",
            len(text),
            len(chunks),
        )
        return chunks

    def _cluster_paragraphs(self, text: str) -> list[str]:
        """Return chunk texts produced by char-overlapping paragraph clustering.

        Every emitted chunk is guaranteed ``<= fallback_chunk_target``. Each
        paragraph is pre-split to the target; the seeded overlap is trimmed so
        ``overlap + sep + para`` still fits. The overlap is redundant context
        (it already lives in the previous chunk), so trimming loses no information.
        """
        target = self.fallback_chunk_target
        paragraphs: list[str] = []
        for para in text.split("\n\n"):
            if len(para) > target:
                paragraphs.extend(self._split_oversized_paragraph(para))
            else:
                paragraphs.append(para)

        chunks: list[str] = []
        current: list[str] = []
        for para in paragraphs:
            sep_len = 2 if current else 0
            if current and len("\n\n".join(current)) + sep_len + len(para) > target:
                # Don't orphan a heading or a list's introducing sentence at the
                # end of the chunk (#678): carry it into the next one instead.
                carried = None
                candidate = current[-1]
                if (
                    len(current) > 1
                    and self._belongs_with_next(candidate, para)
                    and len(candidate) + 2 + len(para) <= target
                ):
                    carried = candidate
                    current = current[:-1]

                chunk_text = "\n\n".join(current)
                chunks.append(chunk_text)
                # Trim the seeded overlap so it can never push the next chunk
                # past target AND can never begin mid-token (#695).
                reserved = len(para) + 2 + (len(carried) + 2 if carried else 0)
                overlap = self._boundary_safe_overlap(chunk_text, target - reserved)
                current = [overlap] if overlap else []
                if carried:
                    current.append(carried)
            current.append(para)

        if current:
            chunks.append("\n\n".join(current))

        return chunks

    def _boundary_safe_overlap(self, chunk_text: str, max_overlap: int) -> str:
        """Return a trailing overlap of ``chunk_text`` that never begins mid-token (#695).

        Takes up to ``fallback_overlap`` trailing chars, capped at ``max_overlap``;
        if that slice would open mid-word, advances its start to the next
        whole-token boundary.
        """
        if max_overlap <= 0:
            return ""
        overlap_len = min(self.fallback_overlap, max_overlap)
        start = max(0, len(chunk_text) - overlap_len)
        start = advance_past_partial_token(chunk_text, start)
        return chunk_text[start:]

    @staticmethod
    def _belongs_with_next(paragraph: str, following: str) -> bool:
        """Return whether ``paragraph`` introduces ``following`` and must stay with it."""
        if is_heading_like_line(paragraph):
            return True
        return is_list_line(following) and not is_list_line(paragraph)

    def _split_oversized_paragraph(
        self,
        text: str,
        separators: tuple[str, ...] = ("\n", " ", ""),
    ) -> list[str]:
        """Split a single paragraph larger than the target without dropping text.

        Tries sentence ends first (#503), then falls back to successively finer
        boundaries: newline, then space, then raw character slicing. An
        unsplittable run is sliced on characters and a warning is logged.
        """
        if len(text) <= self.fallback_chunk_target:
            return [text]

        # Single GFM table paragraphs must be continued with a repeated
        # header/separator, never sliced between rows (#697).
        if is_single_table_block(text):
            return split_table_block(text, self.fallback_chunk_target)

        # Sentence packing is attempted once at the top of the recursion.
        if separators and separators[0] == "\n":
            sentence_pieces = self._split_by_sentences(text, separators)
            if sentence_pieces is not None:
                return sentence_pieces

        sep = separators[0]
        if sep == "":
            logger.warning(
                "Paragraph of %d chars has no whitespace to split on; falling back to character slicing",
                len(text),
            )
            return [text[i : i + self.fallback_chunk_target] for i in range(0, len(text), self.fallback_chunk_target)]

        atoms = text.split(sep)
        if len(atoms) == 1:
            return self._split_oversized_paragraph(text, separators[1:])

        pieces = self._pack_atoms(atoms, sep)

        result: list[str] = []
        for piece in pieces:
            if len(piece) > self.fallback_chunk_target:
                result.extend(self._split_oversized_paragraph(piece, separators[1:]))
            else:
                result.append(piece)
        return result

    def _pack_atoms(self, atoms: list[str], sep: str) -> list[str]:
        """Greedily pack ``atoms`` into pieces of at most the fallback target."""
        pieces: list[str] = []
        current: list[str] = []
        current_size = 0
        for atom in atoms:
            atom_size = len(atom) + len(sep)
            if current and current_size + atom_size > self.fallback_chunk_target:
                pieces.append(sep.join(current))
                current = [atom]
                current_size = atom_size
            else:
                current.append(atom)
                current_size += atom_size
        if current:
            pieces.append(sep.join(current))
        return pieces

    def _split_by_sentences(self, text: str, separators: tuple[str, ...]) -> list[str] | None:
        """Split ``text`` on sentence ends, or return None when fewer than two sentences."""
        pieces = pack_by_sentences(text, self.fallback_chunk_target)
        if pieces is None:
            return None

        result: list[str] = []
        for piece in pieces:
            if len(piece) > self.fallback_chunk_target:
                # Single sentence longer than target — accept the mid-sentence cut.
                result.extend(self._split_oversized_paragraph(piece, separators[1:]))
            else:
                result.append(piece)
        return result

    def _enrich_metadata(self, chunk: Chunk) -> None:
        content = chunk.content
        chunk.metadata["has_table"] = "|---" in content or "| ---" in content
        chunk.metadata["has_note"] = "Unser Tipp" in content or "Bitte beachten Sie" in content

        note_types: list[str] = []
        if "**Unser Tipp**" in content:
            note_types.append("tip")
        if "**Bitte beachten Sie**" in content:
            note_types.append("important")
        if note_types:
            chunk.metadata["note_types"] = note_types
