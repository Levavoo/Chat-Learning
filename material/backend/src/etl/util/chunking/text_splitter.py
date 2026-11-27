"""Shared overlap-aware text splitter for chunking strategies."""

import re

from etl.util.chunking.sentence_boundaries import last_sentence_end
from etl.util.chunking.table_blocks import find_table_spans, split_table_block

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_HEADING_LINE_RE = re.compile(r"^#{1,6}[ \t]+\S")
# A numbered heading, e.g. "3.1.4 Leistungsausschluss". PDF-derived Markdown has
# no "#" headings at all (see #501), so this is the only heading signal there.
_NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*\.?[ \t]+\S")
# A stand-alone bold label such as "**Beispiel:**" — structurally a heading.
_LABEL_LINE_RE = re.compile(r"^\*\*[^*]+:\*\*$")
# Markdown list item (bulleted or ordered). The backslash form appears where
# the Markdown converter escaped a literal asterisk.
_LIST_LINE_RE = re.compile(r"^[ \t]*(?:\\?[*+-][ \t]+|\d+[.)][ \t]+)\S")
_MAX_STRUCTURE_PULLBACKS = 4


def is_list_line(line: str) -> bool:
    """Return whether ``line`` opens a Markdown list item."""
    return bool(_LIST_LINE_RE.match(line.lstrip("\n")))


def is_heading_like_line(line: str) -> bool:
    """Return whether ``line`` is a heading, a numbered heading or a bold label (#678)."""
    stripped = line.strip()
    if not stripped or "\n" in stripped:
        return False
    return bool(
        _HEADING_LINE_RE.match(stripped) or _NUMBERED_HEADING_RE.match(stripped) or _LABEL_LINE_RE.match(stripped)
    )


# Compound/word joiners in forms such as "(Mit-)Arbeit" and "Arbeits-/Sozialrecht".
_TOKEN_JOINERS = "-/("  # noqa: S105


def starts_mid_token(text: str, i: int) -> bool:
    """Return whether cutting ``text`` at index ``i`` would strip a token head (#695)."""
    if not 0 < i < len(text):
        return False
    if not text[i].isalnum():
        return False
    previous = text[i - 1]
    return previous.isalnum() or previous in _TOKEN_JOINERS


_MAX_LINK_LOOKBACK = 2048


def split_text_with_overlap(text: str, max_size: int, overlap: int) -> list[str]:
    r"""Split text into chunks of up to ~``max_size`` chars with overlap.

    Prefers block (newline) boundaries, then real sentence ends, avoids mid-word
    and mid-link splits, never ends a chunk on a heading or between a list and
    its lead-in, and absorbs tiny tail chunks into the previous chunk.

    ``max_size`` is a *soft* limit: chunks may exceed it by up to
    ``max_size // 4 - 1`` chars when a trailing remainder is absorbed, or by
    the length of a Markdown link kept intact.

    Raises:
        ValueError: if ``max_size <= 0`` or ``overlap`` is outside ``[0, max_size)``.

    """
    if max_size <= 0:
        raise ValueError(f"max_size must be > 0, got {max_size}")
    if overlap < 0 or overlap >= max_size:
        raise ValueError(
            f"overlap must satisfy 0 <= overlap < max_size, got overlap={overlap}, max_size={max_size}",
        )

    chunks: list[str] = []
    start = 0
    n = len(text)
    min_chunk = max_size // 2

    while start < n:
        end = min(start + max_size, n)

        if end < n:
            end = _choose_end(text, start, end, max_size)
            end = _avoid_mid_link_split(text, start, end, min_chunk)
            end = _avoid_orphaned_structure(text, start, end, min_chunk)

            if n - end < max_size // 4:
                chunks.append(text[start:n])
                break

        chunks.append(text[start:end])

        if end >= n:
            break

        # START-side analogue of _choose_end (#695): never mid-token.
        next_start = _choose_next_start(text, end, overlap)
        start = _advance_past_link(text, next_start, end)

    return chunks


def split_section_preserving_tables(text: str, max_size: int, overlap: int) -> list[str]:
    """Split like :func:`split_text_with_overlap` but keep every GFM table atomic.

    Prose runs go through :func:`split_text_with_overlap`; tables that fit stay
    whole, oversized tables are continued via
    :func:`etl.util.chunking.table_blocks.split_table_block` (header+separator
    repeated on every piece). No table is ever sliced mid-row (#697).

    Raises:
        ValueError: propagated from :func:`split_text_with_overlap`.

    """
    spans = find_table_spans(text)
    if not spans:
        return split_text_with_overlap(text, max_size, overlap)

    chunks: list[str] = []
    cursor = 0
    for start, end in spans:
        prose = text[cursor:start]
        if prose.strip():
            chunks.extend(split_text_with_overlap(prose, max_size, overlap))
        table = text[start:end]
        if len(table) <= max_size:
            chunks.append(table)
        else:
            chunks.extend(split_table_block(table, max_size))
        cursor = end

    trailing = text[cursor:]
    if trailing.strip():
        chunks.extend(split_text_with_overlap(trailing, max_size, overlap))

    return chunks


def _choose_end(text: str, start: int, end: int, max_size: int) -> int:
    r"""Choose the cut point for a chunk, strongest boundary first.

    DITA -> HTML -> Markdown hard-wraps paragraphs, so a bare ``\\n`` sits
    inside sentences — only a blank line is a real block break (#503).
    """
    block_break = text.rfind("\n\n", start, end)
    if block_break != -1 and block_break > start + (max_size // 2):
        return block_break

    sentence_end = last_sentence_end(text, start + max_size // 4, end)
    if sentence_end is not None:
        return sentence_end

    last_newline = text.rfind("\n", start, end)
    if last_newline != -1 and last_newline > start + (max_size // 2):
        # Sentence longer than the window: keep the line break so the cut lands between words.
        return last_newline

    if end > start and text[end - 1].isalpha() and text[end].isalpha():
        last_space = text.rfind(" ", start + max_size // 4, end)
        if last_space != -1:
            return last_space
    return end


def _avoid_orphaned_structure(text: str, start: int, end: int, min_chunk: int) -> int:
    """Pull ``end`` back so the chunk neither ends on a heading nor cuts a list off its lead-in (#678).

    The offending line moves to the next chunk (where overlap would repeat it
    anyway). Skipped when it would shrink the chunk below ``min_chunk``.
    """
    original = end
    for _ in range(_MAX_STRUCTURE_PULLBACKS):
        segment = text[start:end]
        trimmed = segment.rstrip()
        if not trimmed:
            break

        last_line_start = start + _line_start(segment, len(trimmed))
        last_line = text[last_line_start:end].strip()
        following = text[end:].lstrip("\n").split("\n", 1)[0]

        ends_on_heading = is_heading_like_line(last_line)
        splits_list_lead_in = is_list_line(following) and not is_list_line(last_line)
        if not (ends_on_heading or splits_list_lead_in):
            break

        if last_line_start - start < min_chunk:
            return original
        end = last_line_start
    return end


def _line_start(text: str, position: int) -> int:
    """Return the index of the start of the line containing ``position``."""
    newline = text.rfind("\n", 0, position)
    return newline + 1 if newline != -1 else 0


def _skip_leading_whitespace(text: str, pos: int, limit: int) -> int:
    """Advance ``pos`` past any whitespace without crossing ``limit``."""
    while pos < limit and text[pos].isspace():
        pos += 1
    return pos


def _next_token_start(text: str, pos: int, limit: int) -> int | None:
    """Return the next token start after ``pos``, or None if none exists before ``limit``.

    Skips forward over the current (partial) token to the following whitespace,
    then over that whitespace to the next non-space character.
    """
    i = pos
    while i < limit and not text[i].isspace():
        i += 1
    i = _skip_leading_whitespace(text, i, limit)
    return i if i < limit else None


def advance_past_partial_token(text: str, start: int) -> int:
    """Return ``start`` advanced past a leading partial token, else ``start`` (#695).

    Returns ``len(text)`` when the tail from ``start`` is a single partial
    token with no following whitespace (only redundant overlap is dropped).
    """
    if not starts_mid_token(text, start):
        return start
    token_start = _next_token_start(text, start, len(text))
    return token_start if token_start is not None else len(text)


def _choose_next_start(text: str, end: int, overlap: int) -> int:
    r"""Choose the start of the next chunk, strongest boundary first (#695).

    START-side analogue of ``_choose_end``: never begin a chunk mid-token or
    right after an abbreviation. Preference order:

    1. Abbreviation- and ordinal-aware sentence start.
    2. Block break, then any line break -> whitespace-aligned start.
    3. Advance a mid-token overlap start forward to the next token start.
    4. Degenerate window: raw overlap start.
    """
    overlap_start = max(end - overlap, 0)

    sentence_end = last_sentence_end(text, overlap_start, end)
    if sentence_end is not None:
        opener = _skip_leading_whitespace(text, sentence_end, end)
        return opener if opener < end else sentence_end

    block_break = text.rfind("\n\n", overlap_start, end)
    if block_break != -1:
        return _skip_leading_whitespace(text, block_break, end)
    newline = text.rfind("\n", overlap_start, end)
    if newline != -1:
        return _skip_leading_whitespace(text, newline, end)

    if starts_mid_token(text, overlap_start):
        token_start = _next_token_start(text, overlap_start, end)
        if token_start is not None:
            return token_start

    return overlap_start


def _avoid_mid_link_split(text: str, start: int, end: int, min_chunk: int) -> int:
    """Adjust ``end`` so ``text[start:end]`` does not split a Markdown link.

    When ``end`` falls inside a link ``[text](url)``:

    * If the link begins within the chunk and moving ``end`` back to the
      link's start still leaves at least ``min_chunk`` chars, split before
      the link.
    * Otherwise (link starts at/before ``start``, or pulling back would
      leave too small a chunk), extend ``end`` to the link's end —
      accepting the soft-limit overshoot so the link stays intact.
    """
    search_start = max(0, end - _MAX_LINK_LOOKBACK)
    # endpos must extend past ``end`` so a link straddling it fits fully.
    search_end = min(len(text), end + _MAX_LINK_LOOKBACK)
    for match in _MARKDOWN_LINK_RE.finditer(text, search_start, search_end):
        if match.start() >= end:
            break
        if match.end() <= end:
            continue
        # Link straddles ``end``.
        if match.start() > start and match.start() - start >= min_chunk:
            return match.start()
        return match.end()
    return end


def _advance_past_link(text: str, pos: int, limit: int) -> int:
    """Move ``pos`` forward past any Markdown link it currently sits inside.

    Ensures the next chunk does not begin with a partial ``](url)``
    fragment. ``limit`` (the current chunk's end) bounds the search so we
    never skip past it.
    """
    search_start = max(0, pos - _MAX_LINK_LOOKBACK)
    search_end = min(len(text), pos + _MAX_LINK_LOOKBACK)
    for match in _MARKDOWN_LINK_RE.finditer(text, search_start, search_end):
        if match.end() <= pos:
            continue
        if match.start() < pos < match.end():
            return min(match.end(), limit)
        break
    return pos
