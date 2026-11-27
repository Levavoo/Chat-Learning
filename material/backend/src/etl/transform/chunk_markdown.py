import os
import re
from pathlib import Path
from typing import ClassVar

import yaml

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.base import Transform
from etl.transform.extract_metadata import load_brochure_url_mapping
from etl.util.chunking import (
    ChunkingStrategy,
    FlatSectionChunkingStrategy,
    GlossaryChunkingStrategy,
    HierarchicalChunkingStrategy,
)
from etl.util.chunking.contextual_grounding import apply_contextual_grounding
from etl.util.chunking.llm_enrichment import apply_llm_enrichment
from etl.util.logging_setup import get_logger

_KNOWN_EXTENSIONS = (".md", ".xml", ".html", ".htm", ".txt", ".pdf")


def _strip_known_extension(name: str) -> str:
    lower = name.lower()
    for ext in _KNOWN_EXTENSIONS:
        if lower.endswith(ext):
            return name[: -len(ext)]
    return name


_CONFIG_DIR = Path(__file__).parent.parent / "config"
_BROCHURE_NAMES: dict[str, str] | None = None

# Brochure/Merkblatt ID pattern (B01, F109, FB28, V0090, G0103, R0815).
_BROCHURE_ID_RE = re.compile(r"^[A-Z]{1,2}\d{2,4}$")

# Merkblätter ID prefixes.
_MERKBLATT_PREFIXES = ("G", "R", "V")

# Short-form Merkblatt URL base: https://www.deutsche-rentenversicherung.de/<ID>, derived from ID.
_SHORT_URL_BASE = "https://www.deutsche-rentenversicherung.de"


def _derive_short_brochure_url(brochure_id: str) -> str | None:
    """Derive the short-form public URL for a brochure ID, or None if not derivable."""
    if not _BROCHURE_ID_RE.match(brochure_id):
        return None
    return f"{_SHORT_URL_BASE}/{brochure_id}"


def _load_brochure_names() -> dict[str, str]:
    """Load display name overrides from brochure_names.yaml."""
    global _BROCHURE_NAMES
    if _BROCHURE_NAMES is None:
        path = _CONFIG_DIR / "brochure_names.yaml"
        if path.exists():
            with path.open() as f:
                _BROCHURE_NAMES = yaml.safe_load(f) or {}
        else:
            _BROCHURE_NAMES = {}
    return _BROCHURE_NAMES


class chunk_markdown(Transform):
    """Transform that splits a Markdown document into smaller chunks.

    input_types: MarkdownType
    output_type: MarkdownType
    name: ``CHUNK_MARKDOWN``
    """

    output_type = DataType.MARKDOWN
    supported_input_types: ClassVar[list[DataType]] = [DataType.MARKDOWN]
    transform_type = "CHUNK_MARKDOWN"

    logger = get_logger("CHUNK_MARKDOWN")

    def __init__(self, min_divs_for_hierarchical: int = 3):
        """Initialize the chunking transform.

        Args:
            min_divs_for_hierarchical: Minimum H3 headers used as a
                structural-richness proxy to route into HierarchicalChunkingStrategy.
                Both strategies split at H2 regardless.

        """
        super().__init__()
        self.min_divs_for_hierarchical = min_divs_for_hierarchical

    def apply(self, item: PipelineItem) -> list[PipelineItem]:
        """Apply chunking to the input markdown item."""
        self.logger.debug(f"Chunking {item.data_object.name}")

        content = item.data_object.data
        if isinstance(content, bytes):
            content = content.decode("utf-8")

        if not isinstance(content, str):
            raise TypeError(f"Expected str input for chunking, got {type(content)}")

        metadata = item.data_object.metadata or {}
        self._enrich_metadata_from_filename(item.data_object.name, metadata)
        # Headerless fallback is opt-in per source format: PDFs on, XML off.
        is_pdf = item.source_object.data_type == DataType.PDF
        strategy = self._select_chunking_strategy(content, metadata, enable_headerless_fallback=is_pdf)
        self.logger.info(f"Using chunking strategy: {strategy.__class__.__name__}")
        chunks = strategy.chunk(content, metadata)
        chunks = apply_contextual_grounding(chunks, full_document=content)
        chunks = apply_llm_enrichment(chunks)

        output_items = []
        base_name = _strip_known_extension(item.data_object.name)
        index = 0
        for chunk in chunks:
            # Defensive guard for every strategy: never write a chunk with leading/
            # trailing whitespace. Bedrock's ingestion content-type sniffer (Apache
            # Tika) misdetects a file that begins with a newline followed by "(" as
            # an unsupported binary format and silently drops it ("file format was
            # not supported"). Empty chunks are skipped so indices stay contiguous.
            content = chunk.content.strip()
            if not content:
                continue

            chunk_name = f"{base_name}/{base_name}_{index:04d}"
            index += 1

            chunk_metadata = chunk.metadata.copy()

            new_data_object = DataObject(
                name=chunk_name,
                data=content,
                data_type=DataType.MARKDOWN,
                metadata=chunk_metadata,
            )

            new_item = item.model_copy(update={"data_object": new_data_object, "name": chunk_name})
            output_items.append(new_item)

        self.logger.info(f"Split {item.data_object.name} into {len(output_items)} chunks")
        return output_items

    def _select_chunking_strategy(
        self, markdown: str, metadata: dict, enable_headerless_fallback: bool = False
    ) -> ChunkingStrategy:
        """Select appropriate chunking strategy based on metadata.

        Args:
            markdown: The document content (used for structural routing).
            metadata: Document metadata (brochure_number drives special-cased routing).
            enable_headerless_fallback: Forwarded to FlatSectionChunkingStrategy.
                When True (PDFs), a document with no H2 falls back to H3 / paragraph
                clustering; when False (default, e.g. XML) it stays a single chunk.

        """
        brochure_number = metadata.get("brochure_number", "")

        if brochure_number in ["B28", "B37"]:
            return GlossaryChunkingStrategy()
        elif brochure_number == "B38":
            return FlatSectionChunkingStrategy(enable_headerless_fallback=enable_headerless_fallback)
        elif self._has_hierarchical_sections(markdown):
            return HierarchicalChunkingStrategy()
        else:
            return FlatSectionChunkingStrategy(enable_headerless_fallback=enable_headerless_fallback)

    def _has_hierarchical_sections(self, text: str) -> bool:
        """Heuristic: enough H3 headers to treat the document as structurally rich.

        Used only to choose between HierarchicalChunkingStrategy and
        FlatSectionChunkingStrategy. This routing is independent of chunk
        boundaries: both strategies split at H2. FlatSectionChunkingStrategy
        falls back to H3 boundaries only when its headerless fallback is enabled
        (PDF) and the document has no H2.
        """
        h3_count = text.count("\n### ")
        return h3_count >= self.min_divs_for_hierarchical

    def _enrich_metadata_from_filename(self, item_name: str, metadata: dict) -> None:
        """Set brochure_number, name, and brochure_url from filename if not already present."""
        if metadata.get("brochure_number"):
            return

        # Extract ID from item name (e.g. "IN/V0090" or "V0090.pdf" → "V0090")
        stem = os.path.splitext(os.path.basename(item_name))[0]
        for prefix in ("IN/", "docs/"):
            if stem.startswith(prefix):
                stem = stem[len(prefix) :]

        metadata["brochure_number"] = stem

        if not metadata.get("category") and stem[:1] in _MERKBLATT_PREFIXES:
            metadata["category"] = "Merkblatt"

        names = _load_brochure_names()
        if stem in names:
            metadata["name"] = names[stem]
        elif _BROCHURE_ID_RE.match(stem):
            self.logger.warning(f"No display name mapping for '{stem}' in brochure_names.yaml")

        urls = load_brochure_url_mapping()
        url = urls.get(stem) or urls.get(stem.replace(" ", ""))
        if url:
            metadata["brochure_url"] = url
            short_url = _derive_short_brochure_url(stem)
            if short_url:
                metadata["brochure_url_short"] = short_url
            # else: derivation failure is currently unreachable — any ID matching _BROCHURE_ID_RE
            # always yields a short URL. This guard exists for future regex changes.
        elif _BROCHURE_ID_RE.match(stem):
            self.logger.warning(f"No URL mapping for '{stem}' in brochure_urls.yaml")
