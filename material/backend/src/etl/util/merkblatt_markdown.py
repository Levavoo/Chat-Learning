"""Renderer for the structured Merkblatt Markdown shipped to the Knowledge Base (#501).

Lives in the installed ``etl`` package so both the build-time generator
(``backend/scripts/extract_merkblaetter.py``) and the runtime consumer
(``etl.transform.chunk_markdown``) can import it — ``backend/scripts`` is not
part of the wheel (``tool.hatch.build.targets.wheel``).
"""

import re

# Synthetic heading for an empty-title lead section so it is not silently
# dropped as preamble on the KB H2 chunking path.
SYNTHETIC_INTRO_HEADING = "Überblick"

# Escape stray leading '#' runs so they don't open a spurious H2 section or
# (at >= 3 H3s) flip KB routing to the hierarchical strategy — Merkblatt must
# stay on the flat H2 path.
_LEADING_HASH_RE = re.compile(r"^(#+)(?=\s|$)", re.MULTILINE)


def _neutralise_headings(content: str) -> str:
    return _LEADING_HASH_RE.sub(r"\\\1", content)


def render_sections_to_markdown(doc: dict) -> str:
    """Render un-split ``process_blocks`` sections as flat H2 Markdown for the KB.

    One ``## {title}`` per section — never ``###`` — so the KB ``CHUNK_MARKDOWN``
    transform takes the flat H2 path and emits section-aligned chunks that carry
    ``section_title`` (#501). Sizing of oversized sections is deliberately left
    to that transform; this renderer does NOT pre-split
    (``_split_large_sections`` is only for the agent-search JSON).

    An empty-title lead section gets a synthetic heading — the document title
    when present, else ``Überblick`` — because a bare ``## `` is not a valid H2
    and the chunker discards text before the first H2 as preamble.
    """
    doc_title = (doc.get("title") or "").strip()
    parts: list[str] = []
    for section in doc.get("sections", []):
        title = (section.get("title") or "").strip() or doc_title or SYNTHETIC_INTRO_HEADING
        content = _neutralise_headings((section.get("content") or "").strip())
        content = "\n".join(line.rstrip() for line in content.splitlines())
        body = f"\n\n{content}" if content else ""
        parts.append(f"## {title}{body}\n\n")
    return "".join(parts).rstrip() + "\n" if parts else ""
