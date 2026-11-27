"""Base chunking strategy."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """A chunk of text with metadata."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ChunkingStrategy(ABC):
    @abstractmethod
    def chunk(self, text: str, metadata: dict[str, Any]) -> list[Chunk]:
        pass
