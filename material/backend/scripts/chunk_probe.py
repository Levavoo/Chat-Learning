"""Read-only probe: route a Merkblatt .md (or sibling .pdf) through the real chunker.

Mirrors chunk_markdown._select_chunking_strategy for Markdown sources
(headerless fallback OFF — PDF-only in the live transform).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etl.util.chunking import (
    FlatSectionChunkingStrategy,
    GlossaryChunkingStrategy,
    HierarchicalChunkingStrategy,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_DIR = _REPO_ROOT / "cdk" / "seed-data" / "source"
_DEFAULT_MD = _SOURCE_DIR / "G0103.md"


def _resolve_markdown_path(raw: Path) -> Path:
    """Resolve to the rendered .md; a relative path is retried against the repo root."""
    md = raw.with_suffix(".md") if raw.suffix.lower() == ".pdf" else raw
    if not md.is_absolute() and not md.is_file():
        candidate = _REPO_ROOT / md
        if candidate.is_file():
            return candidate
    return md


def select_strategy(markdown: str, brochure_number: str):
    """Replicate chunk_markdown._select_chunking_strategy for a Markdown source."""
    if brochure_number in ("B28", "B37"):
        return GlossaryChunkingStrategy(), "Glossary (B28/B37 special-case)"
    if brochure_number == "B38":
        return FlatSectionChunkingStrategy(), "Flat (B38 special-case)"
    h3_count = markdown.count("\n### ")
    if h3_count >= 3:
        return HierarchicalChunkingStrategy(), f"Hierarchical (>=3 H3 headers; found {h3_count})"
    return (
        FlatSectionChunkingStrategy(enable_headerless_fallback=False),
        f"Flat H2 path (headerless fallback off; {h3_count} H3 headers)",
    )


def main() -> None:
    """Probe a rendered Merkblatt .md and route it through the chunker."""
    raw_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_MD
    md_path = _resolve_markdown_path(raw_path)
    brochure_id = sys.argv[2] if len(sys.argv) > 2 else md_path.stem

    if not md_path.is_file():
        print(f"ERROR: rendered Markdown not found: {md_path}")
        print("Merkblatt .md files are produced by a live Textract run:")
        print("    make extract-merkblaetter   # needs AWS creds")
        sys.exit(1)

    md = md_path.read_text(encoding="utf-8")

    h2 = md.count("\n## ")
    h3 = md.count("\n### ")
    print(f"\n=== {brochure_id} :: {md_path.name} (rendered Markdown) ===")
    print(f"markdown chars : {len(md):,}")
    print(f"H2 headers (##): {h2}    H3 headers (###): {h3}")

    # --- route + chunk (the real strategy code) ---
    strategy, why = select_strategy(md, brochure_id)
    print(f"strategy chosen: {strategy.__class__.__name__}  ->  {why}")

    chunks = strategy.chunk(md, {"brochure_number": brochure_id, "name": brochure_id})

    sizes = [len(c.content) for c in chunks] or [0]
    over = sum(1 for s in sizes if s > 2500)
    print(f"\n=== Result: {len(chunks)} chunks ===")
    print(f"size chars  -> min {min(sizes):,} | avg {sum(sizes) // len(sizes):,} | max {max(sizes):,}")
    print(f"chunks over 2500-char soft threshold: {over}")

    print("\nidx | chars | type                       | section_title")
    print("----+-------+----------------------------+------------------------------------")
    for i, c in enumerate(chunks):
        t = c.metadata.get("chunk_type", "?")
        title = (c.metadata.get("section_title") or c.metadata.get("glossary_term") or "")[:36]
        print(f"{i:3d} | {len(c.content):5d} | {t:26} | {title}")

    print("\n=== FIRST CHUNK (verbatim, truncated to 600 chars) ===")
    print(chunks[0].content[:600] if chunks else "(no chunks)")


if __name__ == "__main__":
    main()

