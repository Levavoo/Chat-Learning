"""GFM table block detection and atomic splitting.

Pure string functions, no cycle with ``text_splitter`` or the strategies
(``text_splitter``/strategies -> ``table_blocks``). The chunker must never
slice a table between two rows (#697): the Bedrock KB DataSource uses
``chunkingStrategy=NONE``, so a headerless row fragment embeds as meaningless
text and an oversized single-chunk table is silently truncated at the model
token limit. Keeping tables atomic, and continuing an oversized table with a
repeated header/separator, prevents both.
"""

import re

from etl.util.logging_setup import get_logger

logger = get_logger("TABLE_BLOCKS")

# A GFM delimiter row: cells of only '-'/':' separated by '|', >=2 columns,
# >=1 dash per cell. Requires at least one '|' so a bare '---' thematic rule
# and the '---' YAML frontmatter / CONTEXT_SEPARATOR lines never match.
_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)+\|?$")


def is_table_separator_line(line: str) -> bool:
    """Return whether ``line`` is a GFM delimiter row.

    A delimiter row has cells of only dashes/colons separated by pipes, with at
    least two columns and at least one dash per cell (e.g. ``| --- | :--: |`` or
    ``|---|---|``).
    """
    return bool(_SEPARATOR_RE.match(line.strip()))


def is_table_row_line(line: str) -> bool:
    """Return whether ``line`` is a header/data row candidate."""
    stripped = line.strip()
    return bool(stripped) and "|" in stripped


def _column_count(line: str) -> int:
    """Count GFM columns in ``line`` (pipe-split, ignoring one outer pipe per side)."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return len(stripped.split("|"))


def find_table_spans(text: str) -> list[tuple[int, int]]:
    """Return non-overlapping ``(start_char, end_char)`` spans for every GFM table.

    A block starts where a delimiter row follows a non-delimiter row line of
    matching column count, then extends over contiguous row lines until the
    first blank or non-row line. Malformed input yields no span.
    """
    lines = text.split("\n")
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    spans: list[tuple[int, int]] = []
    n = len(lines)
    i = 1
    while i < n:
        if (
            is_table_separator_line(lines[i])
            and is_table_row_line(lines[i - 1])
            and not is_table_separator_line(lines[i - 1])
            and _column_count(lines[i - 1]) == _column_count(lines[i])
        ):
            start_line = i - 1
            j = i + 1
            while j < n and is_table_row_line(lines[j]) and not is_table_separator_line(lines[j]):
                j += 1
            start_char = offsets[start_line]
            end_char = offsets[j] if j < n else len(text)
            spans.append((start_char, end_char))
            i = j + 1
        else:
            i += 1
    return spans


def is_single_table_block(text: str) -> bool:
    """Return whether ``text`` is essentially one GFM table (one span covering every non-blank line)."""
    spans = find_table_spans(text)
    if len(spans) != 1:
        return False
    start, end = spans[0]
    return not text[:start].strip() and not text[end:].strip()


def split_table_block(table_text: str, max_size: int) -> list[str]:
    """Split ONE table into pieces ``<= max_size``, each led by the same header+separator.

    Data rows are packed greedily; a row is never split. A header+separator+row
    that already exceeds ``max_size`` is emitted oversized (cutting mid-cell
    would produce an invalid table). Returns ``[table_text.strip()]`` when the
    input is not a header+separator table or has no data rows.
    """
    stripped = table_text.strip()
    lines = stripped.split("\n")
    if len(lines) < 3 or not is_table_separator_line(lines[1]):
        return [stripped]

    prefix = f"{lines[0]}\n{lines[1]}"
    prefix_len = len(prefix)
    data_rows = lines[2:]

    pieces: list[str] = []
    current: list[str] = []
    current_len = prefix_len

    for row in data_rows:
        row_add = len(row) + 1
        if current and current_len + row_add > max_size:
            pieces.append("\n".join([prefix, *current]))
            current = []
            current_len = prefix_len

        current.append(row)
        current_len += row_add

        if len(current) == 1 and current_len > max_size:
            logger.warning(
                "Table row exceeds max_size (%d > %d chars); emitting oversized piece rather than cutting mid-cell",
                current_len,
                max_size,
            )
            pieces.append("\n".join([prefix, *current]))
            current = []
            current_len = prefix_len

    if current:
        pieces.append("\n".join([prefix, *current]))

    return pieces
