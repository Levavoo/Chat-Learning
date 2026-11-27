
import pytest

from etl.util.chunking.table_blocks import is_table_row_line, is_table_separator_line
from etl.util.chunking.text_splitter import (
    _choose_next_start,
    split_section_preserving_tables,
    split_text_with_overlap,
    starts_mid_token,
)


class TestParameterValidation:

    def test_raises_on_zero_max_size(self):
        with pytest.raises(ValueError, match="max_size must be > 0"):
            split_text_with_overlap("abc", max_size=0, overlap=0)

    def test_raises_on_negative_max_size(self):
        with pytest.raises(ValueError, match="max_size must be > 0"):
            split_text_with_overlap("abc", max_size=-1, overlap=0)

    def test_raises_on_overlap_equal_max_size(self):
        with pytest.raises(ValueError, match="overlap must satisfy"):
            split_text_with_overlap("abc" * 100, max_size=10, overlap=10)

    def test_raises_on_overlap_greater_than_max_size(self):
        with pytest.raises(ValueError, match="overlap must satisfy"):
            split_text_with_overlap("abc" * 100, max_size=10, overlap=20)

    def test_raises_on_negative_overlap(self):
        with pytest.raises(ValueError, match="overlap must satisfy"):
            split_text_with_overlap("abc", max_size=10, overlap=-1)


class TestBasicSplitting:

    def test_empty_string_returns_empty_list(self):
        assert split_text_with_overlap("", max_size=100, overlap=10) == []

    def test_text_shorter_than_max_size_is_single_chunk(self):
        text = "short text"
        chunks = split_text_with_overlap(text, max_size=100, overlap=10)
        assert chunks == [text]

    def test_text_exactly_max_size_is_single_chunk(self):
        text = "a" * 100
        chunks = split_text_with_overlap(text, max_size=100, overlap=10)
        assert chunks == [text]

    def test_max_size_one_does_not_loop(self):
        chunks = split_text_with_overlap("abcd", max_size=1, overlap=0)
        assert "".join(chunks).replace(" ", "") == "abcd" or "abcd" in "".join(chunks)
        assert len(chunks) >= 1

    def test_concatenated_chunks_cover_input(self):
        text = "word " * 500
        chunks = split_text_with_overlap(text, max_size=100, overlap=20)
        assert len(chunks) > 1
        # Walk chunks in order; every position in text should be reachable.
        rebuilt = chunks[0]
        for c in chunks[1:]:
            # Each following chunk must overlap with or immediately follow prior content.
            assert c in text
            rebuilt += c
        assert text[:50] in rebuilt
        assert text[-50:] in rebuilt


class TestOverlap:

    def test_consecutive_chunks_share_content(self):
        text = "word " * 500
        chunks = split_text_with_overlap(text, max_size=200, overlap=50)
        assert len(chunks) > 1
        for i in range(len(chunks) - 1):
            tail = chunks[i][-50:]
            head = chunks[i + 1][:100]
            assert set(tail.split()) & set(head.split())

    def test_overlap_prefers_sentence_boundary(self):
        text = "Sentence one. Sentence two. " * 40
        chunks = split_text_with_overlap(text, max_size=150, overlap=50)
        assert len(chunks) > 1
        for follow in chunks[1:]:
            # Sentence-aligned starts begin with a capital letter (ignoring leading ws)
            stripped = follow.lstrip()
            assert stripped and stripped[0].isupper()


class TestBoundaryPreference:

    def test_prefers_newline_boundary(self):
        text = "Line content here.\n" * 50
        chunks = split_text_with_overlap(text, max_size=100, overlap=20)
        for chunk in chunks[:-1]:
            assert chunk.endswith("\n") or chunk.rstrip().endswith(".")

    def test_does_not_split_mid_word(self):
        long_word = "Versorgungsausgleichskassengesetz"
        text = ("ab " * 30) + long_word + " " + ("cd " * 50)
        chunks = split_text_with_overlap(text, max_size=100, overlap=0)
        assert any(long_word in c for c in chunks)


class TestTailAbsorption:

    def test_small_tail_is_absorbed(self):
        text = "a" * 1000 + " tail"
        chunks = split_text_with_overlap(text, max_size=1000, overlap=100)
        assert len(chunks) == 1
        assert chunks[0].endswith("tail")

    def test_soft_limit_overshoot_is_bounded(self):
        text = "a" * 1100
        chunks = split_text_with_overlap(text, max_size=1000, overlap=100)
        max_allowed = 1000 + 1000 // 4
        assert all(len(c) < max_allowed for c in chunks)


class TestMarkdownLinkHandling:

    @staticmethod
    def _contains_partial_link(chunk: str) -> bool:
        state = "text"
        for i, ch in enumerate(chunk):
            if state == "text" and ch == "[":
                state = "link_text"
            elif state == "link_text" and ch == "]":
                state = "link_url" if i + 1 < len(chunk) and chunk[i + 1] == "(" else "text"
            elif state == "link_url" and ch == ")":
                state = "text"
        return state != "text"

    def test_no_chunk_contains_partial_link_when_link_starts_in_chunk(self):
        link = "[Label](https://example.com/some/long/path.html)"
        text = ("x" * 280) + link + ("y" * 200)
        chunks = split_text_with_overlap(text, max_size=300, overlap=30)
        for chunk in chunks:
            assert not self._contains_partial_link(chunk), f"partial link in chunk: {chunk!r}"

    def test_no_chunk_starts_with_partial_link_fragment(self):
        # Link immediately after a small prefix; max_size + overlap chosen so
        # a naive start = end - overlap would land inside the link.
        link = "[A very long link label text](https://example.com/path/that/is/fairly/long.html)"
        text = "intro text. " + link + " " + ("word " * 200)
        chunks = split_text_with_overlap(text, max_size=120, overlap=60)
        for chunk in chunks:
            assert not self._contains_partial_link(chunk), f"partial link in chunk: {chunk!r}"

    def test_link_longer_than_max_size_kept_intact(self):
        long_link = "[Label](" + ("a" * 200) + ")"
        text = "prefix " + long_link + " suffix " + ("word " * 200)
        chunks = split_text_with_overlap(text, max_size=100, overlap=20)
        assert any(long_link in c for c in chunks), "long link was split across chunks"


class TestProgressInvariants:

    def test_all_punctuation_does_not_loop(self):
        chunks = split_text_with_overlap("." * 1000, max_size=50, overlap=10)
        assert len(chunks) > 0

    def test_all_whitespace_does_not_loop(self):
        chunks = split_text_with_overlap(" " * 1000, max_size=50, overlap=10)
        assert len(chunks) > 0

    def test_single_long_word_does_not_loop(self):
        chunks = split_text_with_overlap("a" * 1000, max_size=100, overlap=20)
        assert len(chunks) > 0
        assert sum(len(c) for c in chunks) >= 1000


class TestSentenceAwareBoundaries:

    def test_hard_wrapped_paragraph_is_cut_at_a_sentence_end(self):
        sentences = [
            "Die Wartezeit von fünf Jahren ist eine Voraussetzung für die Rente.",
            "Solche Zeiten sind dann gegebenenfalls anzurechnen und werden geprüft.",
            "Folgende Renten kommen grundsätzlich für Versicherte in Betracht.",
            "Der Rentenversicherungsträger entscheidet über Art und Umfang der Leistung.",
        ]
        # Hard-wrap every sentence across lines, as the DITA -> MD conversion does.
        text = "\n".join(word_group for s in sentences for word_group in _wrap(s, 40))
        chunks = split_text_with_overlap(text, max_size=120, overlap=30)
        assert len(chunks) > 1
        for chunk in chunks[:-1]:
            assert chunk.rstrip().endswith("."), f"chunk ends mid-sentence: {chunk!r}"

    def test_abbreviation_is_not_used_as_a_cut_point(self):
        text = (
            "Das gilt z. B. für Versicherte mit Kindern und weiteren Angehörigen. "
            "Die Nr. 5 der Anlage regelt die Einzelheiten dieser Sonderregelung. "
            "Danach folgt ein weiterer vollständiger Satz für den Test."
        )
        chunks = split_text_with_overlap(text, max_size=120, overlap=20)
        for chunk in chunks[:-1]:
            stripped = chunk.rstrip()
            assert not stripped.endswith("z. B."), f"cut after abbreviation: {chunk!r}"
            assert not stripped.endswith("Nr."), f"cut after abbreviation: {chunk!r}"

    def test_block_break_is_preferred_over_line_break(self):
        text = "Erster Absatz Zeile eins\nZeile zwei des Absatzes.\n\nZweiter Absatz beginnt hier und ist länger."
        chunks = split_text_with_overlap(text, max_size=60, overlap=10)
        assert chunks[0].rstrip().endswith(".")


class TestOrphanedStructure:

    def test_chunk_does_not_end_on_a_heading(self):
        body = "Dies ist ein längerer Absatz mit Inhalt zur Rentenversicherung. " * 4
        text = f"{body}\n\n### Beiträge\n\nBeiträge zahlen Arbeitnehmer und Arbeitgeber gemeinsam."
        chunks = split_text_with_overlap(text, max_size=300, overlap=60)
        for chunk in chunks:
            last_line = [line for line in chunk.split("\n") if line.strip()][-1].strip()
            assert not last_line.startswith("#"), f"chunk ends on a heading: {chunk!r}"

    def test_chunk_does_not_end_on_a_bold_label(self):
        body = "Dies ist ein längerer Absatz mit Inhalt zur Rentenversicherung. " * 4
        text = f"{body}\n\n**Beispiel:**\n\nEine Versicherte zahlt Beiträge über 45 Jahre."
        chunks = split_text_with_overlap(text, max_size=300, overlap=60)
        for chunk in chunks:
            last_line = [line for line in chunk.split("\n") if line.strip()][-1].strip()
            assert last_line != "**Beispiel:**", f"chunk ends on a label: {chunk!r}"

    def test_list_stays_with_its_lead_in(self):
        body = "Dies ist ein längerer Absatz mit Inhalt zur Rentenversicherung. " * 4
        lead_in = "Nach der Bewilligung erhalten Sie von der Rehabilitationseinrichtung"
        text = f"{body}\n\n{lead_in}\n\n* eine Mitteilung über den Beginn und\n* Informationen zur Anreise."
        chunks = split_text_with_overlap(text, max_size=300, overlap=60)
        for chunk in chunks:
            if lead_in in chunk:
                assert "* eine Mitteilung" in chunk, f"lead-in split from its list: {chunk!r}"

    def test_pull_back_is_skipped_when_it_would_starve_the_chunk(self):
        text = "kurz\n\n### Überschrift\n\n" + ("Inhalt " * 200)
        chunks = split_text_with_overlap(text, max_size=100, overlap=20)
        assert len(chunks) > 1
        assert "".join(chunks)


class TestTableAtomicity:

    @staticmethod
    def _starts_with_headerless_row(chunk: str) -> bool:
        lines = chunk.lstrip("\n").split("\n")
        first = lines[0]
        if not is_table_row_line(first) or is_table_separator_line(first):
            return False
        # A leading table row is legitimate only as a header immediately followed
        # by a delimiter row; anything else is a headerless fragment (#697).
        return not (len(lines) > 1 and is_table_separator_line(lines[1]))

    def test_table_free_text_is_byte_for_byte_unchanged(self):
        text = "Ein vollständiger Satz zur Rente. " * 200
        assert split_section_preserving_tables(text, 200, 40) == split_text_with_overlap(text, 200, 40)

    def test_embedded_table_is_not_sliced(self):
        prose = "Dies ist ein Satz zur Rentenversicherung. " * 20
        table = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
        text = f"{prose}\n\n{table}\n\n{prose}"

        chunks = split_section_preserving_tables(text, 2500, 300)

        assert sum(table in chunk for chunk in chunks) == 1, "table must appear intact in exactly one chunk"
        assert not any(self._starts_with_headerless_row(chunk) for chunk in chunks)

    def test_oversized_table_is_continued_with_repeated_header(self):
        header = "| Jahr | Wert |"
        separator = "| --- | --- |"
        rows = [f"| {2000 + i} | {i * 7:04d} |" for i in range(200)]
        text = f"{header}\n{separator}\n" + "\n".join(rows)

        chunks = split_section_preserving_tables(text, 2500, 300)

        assert len(chunks) > 1
        reconstructed: list[str] = []
        for chunk in chunks:
            lines = chunk.split("\n")
            assert lines[0] == header
            assert lines[1] == separator
            reconstructed.extend(lines[2:])
        assert reconstructed == rows, "every row must survive in order across continuations"
        assert not any(self._starts_with_headerless_row(chunk) for chunk in chunks)

    def test_no_chunk_starts_with_a_lone_pipe_fragment(self):
        header = "| Die Zuschläge betragen | EP |"
        separator = "| --- | --- |"
        rows = [f"| Zeile {i} mit etwas Kontext | {i},3258 EP |" for i in range(120)]
        text = f"{header}\n{separator}\n" + "\n".join(rows)

        chunks = split_section_preserving_tables(text, 1500, 200)

        assert len(chunks) > 1
        for chunk in chunks:
            first = chunk.lstrip("\n").split("\n")[0]
            assert first != "|", f"chunk starts with a lone pipe: {chunk[:40]!r}"
            assert not self._starts_with_headerless_row(chunk), f"headerless row start: {chunk[:60]!r}"

    def test_prose_around_table_still_splits_normally(self):
        prose = "Ein vollständiger Satz zur Rentenversicherung. " * 40
        table = "| Beitrag | Satz |\n| --- | --- |\n| 2023 | 18,6 |\n| 2024 | 18,6 |"
        text = f"{prose}\n\n{table}\n\n{prose}"

        chunks = split_section_preserving_tables(text, 500, 80)

        assert len(chunks) > 2, "long prose on both sides must produce several chunks"
        assert sum(table in chunk for chunk in chunks) == 1
        assert not any(self._starts_with_headerless_row(chunk) for chunk in chunks)


def _wrap(sentence: str, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in sentence.split(" "):
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


class TestStartsMidToken:

    @pytest.mark.parametrize(
        ("word", "cut_after"),
        [
            ("Betreuung", 3),  # -> "reuung"
            ("berufsunfähig", 6),  # -> "sunfähig" (ä is Unicode-alnum)
            ("Rentenversicherungsträger", 7),  # -> "ersicherungsträger"
            ("Informationen", 2),  # -> "formationen"
        ],
    )
    def test_true_when_cut_strips_a_word_head(self, word, cut_after):
        text = f"Vorwort {word} Nachwort"
        i = text.index(word) + cut_after
        assert starts_mid_token(text, i)

    def test_true_for_compound_joiner(self):
        # The reported '(Mit-)Arbeit' -> 'it-)Arbeit' shape: cut after "M".
        text = "die (Mit-)Arbeit zählt"
        assert starts_mid_token(text, text.index("Mit-)") + 1)
        # A '/' compound joiner, e.g. "Arbeits-/Sozialrecht" -> "Sozialrecht".
        compound = "das Arbeits-/Sozialrecht hier"
        assert starts_mid_token(compound, compound.index("Sozialrecht"))

    def test_false_at_whitespace_and_word_start(self):
        text = "Wort eins zwei"
        assert not starts_mid_token(text, text.index(" eins"))  # on the space
        assert not starts_mid_token(text, text.index("eins"))  # 'e' preceded by space

    def test_false_at_bounds(self):
        text = "abc"
        assert not starts_mid_token(text, 0)
        assert not starts_mid_token(text, len(text))


class TestChooseNextStart:

    def test_b2_prefers_real_sentence_over_abbreviation(self):
        text = "Ein vollständiger einleitender Satz. Das gilt z. B. für Versicherte."
        end = text.index("Versicherte")
        overlap = end  # window covers the whole prefix
        start = _choose_next_start(text, end, overlap)
        assert start == text.index("Das")
        assert not text[start:].startswith("für")

    def test_b1_advances_past_a_mid_token_overlap_start(self):
        text = "Vorwort Betreuung und Therapie Nachwort"
        assert "." not in text and "\n" not in text
        end = text.index(" Nachwort")  # keep "und Therapie" inside the window
        mid = text.index("Betreuung") + 3  # after "Bet"
        overlap = end - mid
        assert starts_mid_token(text, mid)  # the naive fallback would land here
        start = _choose_next_start(text, end, overlap)
        assert not starts_mid_token(text, start)
        assert text[start:].startswith("und ")

    def test_prefers_block_break(self):
        text = "erster block ohne satzende\n\nzweiter block folgt hier weiter"
        end = len(text)
        overlap = len(text) - text.index("erster")
        start = _choose_next_start(text, end, overlap)
        assert text[start:].startswith("zweiter block")

    def test_degenerate_single_token_window_keeps_overlap_start(self):
        text = "abcdefghijklmnop"
        end = len(text)
        overlap = 5
        start = _choose_next_start(text, end, overlap)
        assert start == end - overlap


class TestSentenceAwareStarts:
    """#695: chunk STARTS must be boundary-safe, mirroring #503's END fix.

    Guards the five reported mid-word fragments and asserts no generated
    sub-chunk begins mid-token.
    """

    _REPORTED_FRAGMENTS = ("it-)Arbeit", "sunfähig", "ersicherungsträger", "formationen", "reuung")
    _WORDS = ("(Mit-)Arbeit", "berufsunfähig", "Rentenversicherungsträger", "Informationen", "Betreuung")

    @staticmethod
    def _start_offsets(text: str, chunks: list[str]) -> list[int]:
        offsets: list[int] = []
        cursor = 0
        for chunk in chunks:
            idx = text.index(chunk, cursor)
            offsets.append(idx)
            cursor = idx + 1
        return offsets

    def test_no_chunk_starts_mid_token_on_boundaryless_text(self):
        text = " ".join(f"Abschnitt{i:03d} {self._WORDS[i % len(self._WORDS)]}" for i in range(80))
        assert "." not in text and "\n" not in text
        chunks = split_text_with_overlap(text, max_size=120, overlap=40)
        assert len(chunks) > 1
        for offset in self._start_offsets(text, chunks):
            assert not starts_mid_token(text, offset), f"mid-token start: {text[offset : offset + 30]!r}"

    def test_reported_fragments_never_open_a_chunk(self):
        text = " ".join(f"Teil{i:03d} {self._WORDS[i % len(self._WORDS)]} folgt" for i in range(100))
        chunks = split_text_with_overlap(text, max_size=90, overlap=30)
        for chunk in chunks:
            stripped = chunk.lstrip()
            for fragment in self._REPORTED_FRAGMENTS:
                assert not stripped.startswith(fragment), f"malformed start {fragment!r}: {stripped[:40]!r}"

    def test_reported_words_survive_intact(self):
        text = " ".join(f"Teil{i:03d} {self._WORDS[i % len(self._WORDS)]} folgt" for i in range(100))
        chunks = split_text_with_overlap(text, max_size=90, overlap=30)
        joined = "".join(chunks)
        for word in self._WORDS:
            assert word in joined, f"word lost/fragmented: {word!r}"

    def test_boundaryless_input_terminates_and_covers(self):
        text = " ".join(f"Wort{i:03d} {self._WORDS[i % len(self._WORDS)]}" for i in range(60))
        chunks = split_text_with_overlap(text, max_size=100, overlap=30)
        covered = bytearray(len(text))
        cursor = 0
        for chunk in chunks:
            idx = text.index(chunk, cursor)
            for j in range(idx, idx + len(chunk)):
                covered[j] = 1
            cursor = idx + 1
        assert all(covered), "gap in coverage after mid-token forward-advance"
