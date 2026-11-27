
import logging

from etl.util.chunking.table_blocks import (
    _column_count,
    find_table_spans,
    is_single_table_block,
    is_table_row_line,
    is_table_separator_line,
    split_table_block,
)


class TestIsTableSeparatorLine:

    def test_compact_form(self):
        assert is_table_separator_line("|---|---|")

    def test_spaced_form(self):
        assert is_table_separator_line("| --- | --- |")

    def test_aligned_form(self):
        assert is_table_separator_line("|:--|--:|")

    def test_centered_aligned_form(self):
        assert is_table_separator_line("| :---: | :---: |")

    def test_without_outer_pipes(self):
        assert is_table_separator_line("--- | ---")

    def test_thematic_rule_is_not_a_separator(self):
        assert not is_table_separator_line("---")

    def test_single_column_is_not_a_separator(self):
        assert not is_table_separator_line("| --- |")

    def test_header_row_is_not_a_separator(self):
        assert not is_table_separator_line("| A | B |")

    def test_blank_is_not_a_separator(self):
        assert not is_table_separator_line("")

    def test_prose_is_not_a_separator(self):
        assert not is_table_separator_line("regular text | with a pipe")


class TestIsTableRowLine:

    def test_full_row(self):
        assert is_table_row_line("| A | B |")

    def test_row_without_outer_pipes(self):
        assert is_table_row_line("A | B")

    def test_lone_pipe(self):
        assert is_table_row_line("|")

    def test_no_pipe(self):
        assert not is_table_row_line("no pipe here")

    def test_blank(self):
        assert not is_table_row_line("   ")


class TestColumnCount:

    def test_two_columns_with_outer_pipes(self):
        assert _column_count("| A | B |") == 2

    def test_three_columns(self):
        assert _column_count("| A | B | C |") == 3

    def test_no_outer_pipes(self):
        assert _column_count("A | B") == 2

    def test_compact_separator(self):
        assert _column_count("|---|---|") == 2


class TestFindTableSpans:

    def test_single_table(self):
        text = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n"
        spans = find_table_spans(text)
        assert len(spans) == 1
        start, end = spans[0]
        assert text[start:end].strip() == "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"

    def test_table_embedded_in_prose(self):
        text = "Intro prose.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nOutro prose."
        spans = find_table_spans(text)
        assert len(spans) == 1
        start, end = spans[0]
        assert text[:start].strip() == "Intro prose."
        assert text[start:end].strip() == "| A | B |\n|---|---|\n| 1 | 2 |"
        assert text[end:].strip() == "Outro prose."

    def test_two_tables(self):
        text = "| A | B |\n|---|---|\n| 1 | 2 |\n\n| C | D |\n|---|---|\n| 3 | 4 |"
        assert len(find_table_spans(text)) == 2

    def test_thematic_rule_is_not_a_table(self):
        assert find_table_spans("first paragraph\n---\nsecond paragraph") == []

    def test_yaml_frontmatter_is_not_a_table(self):
        assert find_table_spans("---\ntitle: Foo\n---\n\nbody text") == []

    def test_lone_pipe_is_not_a_table(self):
        assert find_table_spans("|") == []

    def test_header_without_separator_is_not_a_table(self):
        assert find_table_spans("| just | a | header |\nplain prose follows") == []

    def test_column_count_mismatch_is_not_a_table(self):
        assert find_table_spans("| A | B | C |\n| --- | --- |\n| 1 | 2 |") == []

    def test_empty_text(self):
        assert find_table_spans("") == []


class TestIsSingleTableBlock:

    def test_pure_table(self):
        assert is_single_table_block("| A | B |\n|---|---|\n| 1 | 2 |") is True

    def test_table_with_surrounding_prose(self):
        assert is_single_table_block("Intro.\n\n| A | B |\n|---|---|\n| 1 | 2 |") is False

    def test_no_table(self):
        assert is_single_table_block("no table here at all") is False


class TestSplitTableBlock:

    HEADER = "| Jahr | Wert |"
    SEPARATOR = "| --- | --- |"

    def _rows(self, count: int) -> list[str]:
        return [f"| {2000 + i} | {i * 7:04d} |" for i in range(count)]

    def test_small_table_is_single_piece(self):
        table = f"{self.HEADER}\n{self.SEPARATOR}\n" + "\n".join(self._rows(3))
        pieces = split_table_block(table, max_size=2500)
        assert pieces == [table]

    def test_oversized_table_repeats_header_and_preserves_rows(self):
        rows = self._rows(200)
        table = f"{self.HEADER}\n{self.SEPARATOR}\n" + "\n".join(rows)
        assert len(table) > 2500

        pieces = split_table_block(table, max_size=2500)

        assert len(pieces) > 1
        reconstructed: list[str] = []
        for piece in pieces:
            lines = piece.split("\n")
            assert lines[0] == self.HEADER
            assert lines[1] == self.SEPARATOR
            assert len(piece) <= 2500
            reconstructed.extend(lines[2:])
        assert reconstructed == rows

    def test_wide_single_row_overshoots_with_warning(self, caplog):
        wide_row = "| " + ("x" * 300) + " | y |"
        table = f"{self.HEADER}\n{self.SEPARATOR}\n{wide_row}"

        with caplog.at_level(logging.WARNING):
            pieces = split_table_block(table, max_size=50)

        assert len(pieces) == 1
        assert wide_row in pieces[0]
        assert ("x" * 300) in pieces[0], "cell must never be cut mid-content"
        assert "exceeds max_size" in caplog.text

    def test_header_only_table_passes_through(self):
        table = f"{self.HEADER}\n{self.SEPARATOR}"
        assert split_table_block(table, max_size=100) == [table]

    def test_non_table_input_passes_through(self):
        text = "just some prose\nwith two lines"
        assert split_table_block(text, max_size=100) == [text]
