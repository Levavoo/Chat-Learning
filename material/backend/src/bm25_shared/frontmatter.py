"""Shared helper for stripping a leading YAML frontmatter block.

The ETL write boundary (``TEXT2MD``) no longer prepends frontmatter to chunk
bodies (#696), so the index-time (BM25) and query-time (orchestrator) strips that
reuse this helper operate on already-clean bytes. They are kept as defensive,
idempotent no-ops that still protect any not-yet-reprocessed content and any
future path — one regex, one contract, no drift.
"""

import re

# A leading YAML frontmatter block: `---\n … \n---`, plus any trailing blank lines.
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n*", re.DOTALL)


def strip_frontmatter(text: str) -> str:
    """Remove a leading YAML frontmatter block. Idempotent; a no-op when absent."""
    return _FRONTMATTER_RE.sub("", text)
