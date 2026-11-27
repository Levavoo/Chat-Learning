"""Glossary entry chunking strategy."""

from typing import Any

from etl.util.chunking.base import Chunk, ChunkingStrategy


class GlossaryChunkingStrategy(ChunkingStrategy):
    """Chunks glossary documents into term-definition pairs."""

    def chunk(self, text: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Chunk glossary content into term-definition pairs."""
        chunks = []
        paragraphs = text.split("\n\n")

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
        """Check if text appears to be a glossary term."""
        clean = text.strip()
        if len(clean) > 80:
            return False

        return not (clean.endswith(".") or clean.endswith(":"))

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
