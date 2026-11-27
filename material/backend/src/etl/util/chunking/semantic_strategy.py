"""Semantic/fallback chunking strategy."""

from typing import Any

from etl.util.chunking.base import Chunk, ChunkingStrategy


class SemanticChunkingStrategy(ChunkingStrategy):
    """Generic fallback chunking strategy."""

    def chunk(self, text: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Chunk content using generic/semantic approach."""
        chunk = Chunk(content=text, metadata=metadata.copy())
        chunk.metadata.update({
            "chunk_type": "semantic_fallback",
        })
        self._enrich_metadata(chunk)

        return [chunk]

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
