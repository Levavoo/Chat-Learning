
import logging

import pytest

from etl.util.chunking.flat_section_strategy import FlatSectionChunkingStrategy
from etl.util.chunking.table_blocks import is_table_row_line, is_table_separator_line
from etl.util.chunking.text_splitter import starts_mid_token


def _starts_with_headerless_row(content: str) -> bool:
    lines = content.lstrip("\n").split("\n")
    first = lines[0]
    if not is_table_row_line(first) or is_table_separator_line(first):
        return False
    return not (len(lines) > 1 and is_table_separator_line(lines[1]))


class TestFlatSectionChunkingStrategyChunk:

    @pytest.fixture
    def strategy(self):
        return FlatSectionChunkingStrategy()

    def test_returns_single_chunk_for_text_without_sections(self, strategy, base_metadata):
        text = "Just plain text without any headers."
        chunks = strategy.chunk(text, base_metadata)
        assert len(chunks) == 1
        assert chunks[0].content == text

    def test_splits_by_h2_sections(self, strategy, markdown_with_h2_sections, base_metadata):
        chunks = strategy.chunk(markdown_with_h2_sections, base_metadata)
        assert len(chunks) == 3
        assert all("section_title" in c.metadata for c in chunks)

    def test_chunk_type_is_flat_section(self, strategy, markdown_with_h2_sections, base_metadata):
        chunks = strategy.chunk(markdown_with_h2_sections, base_metadata)
        assert all(c.metadata["chunk_type"] == "flat_section" for c in chunks)

    def test_preserves_source_metadata(self, strategy, markdown_with_h2_sections, base_metadata):
        chunks = strategy.chunk(markdown_with_h2_sections, base_metadata)
        for chunk in chunks:
            assert chunk.metadata["source"] == "test.md"
            assert chunk.metadata["doc_type"] == "test"

    def test_section_titles_extracted_correctly(self, strategy, markdown_with_h2_sections, base_metadata):
        chunks = strategy.chunk(markdown_with_h2_sections, base_metadata)
        titles = [c.metadata["section_title"] for c in chunks]
        assert "Section One" in titles
        assert "Section Two" in titles
        assert "Section Three" in titles


class TestFlatSectionChunkingStrategySplitting:

    def test_large_section_is_split(self, large_section_content, base_metadata):
        strategy = FlatSectionChunkingStrategy(section_split_threshold=500, section_overlap=50)
        chunks = strategy.chunk(large_section_content, base_metadata)
        assert len(chunks) > 1
        assert all(c.metadata["chunk_type"] == "flat_section_split" for c in chunks)

    def test_split_chunks_have_overlap(self, base_metadata):
        text = "## Section\n\n" + "word " * 1000
        strategy = FlatSectionChunkingStrategy(section_split_threshold=500, section_overlap=100)
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) > 1
        for i in range(len(chunks) - 1):
            chunk1_end = chunks[i].content[-100:]
            chunk2_start = chunks[i + 1].content[:200]
            assert len(set(chunk1_end.split()) & set(chunk2_start.split())) > 0

    def test_overlap_includes_last_sentence(self, base_metadata):
        text = "## Section\n\n" + "Word. " * 50 + "End sentence."
        strategy = FlatSectionChunkingStrategy(section_split_threshold=100, section_overlap=50)
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) > 1
        last_chunk_0 = chunks[0].content.rstrip()
        last_dot = last_chunk_0.rfind(".")
        prev_space = last_chunk_0.rfind(" ", 0, last_dot)
        start_idx = 0 if prev_space == -1 else prev_space + 1
        last_sentence = last_chunk_0[start_idx : last_dot + 1]
        next_start = chunks[1].content.lstrip()
        assert next_start.startswith(last_sentence), (
            f"Expected chunk 1 to start with {last_sentence!r}, got {next_start[:50]!r}"
        )

    def test_split_prefers_newline_boundaries(self, base_metadata):
        text = "## Section\n\n" + "Line one content.\nLine two content.\n" * 100
        strategy = FlatSectionChunkingStrategy(section_split_threshold=200, section_overlap=20)
        chunks = strategy.chunk(text, base_metadata)

        for chunk in chunks[:-1]:
            assert chunk.content.rstrip().endswith(".") or chunk.content.endswith("\n")

    def test_no_tiny_orphan_tail_chunk(self, base_metadata):
        # 3000 chars of body + 100-char tail — tail is < max_size // 4 (750), so no split
        text = "## Section\n\n" + "a " * 1500 + "\n\nKurzer Schlusssatz."
        strategy = FlatSectionChunkingStrategy(section_split_threshold=3000, section_overlap=100)
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
        assert "Kurzer Schlusssatz." in chunks[0].content

    def test_does_not_split_mid_word(self, base_metadata):
        long_word = "Versorgungsausgleich"
        # "ab " * 32 = 96 chars, so naive char split at 100 lands inside the long word
        text = "## S\n\n" + ("ab " * 32) + long_word + " " + ("cd " * 50)
        strategy = FlatSectionChunkingStrategy(section_split_threshold=100, section_overlap=0)
        chunks = strategy.chunk(text, base_metadata)

        assert any(long_word in c.content for c in chunks), "Long word was split across chunks"

    def test_does_not_split_inside_markdown_link(self, base_metadata):
        padding = "x" * 280
        link = "[Titel der Broschüre](https://www.deutsche-rentenversicherung.de/some-long-path.html)"
        text = f"## Section\n\n{padding}\n{link}\nMore text after link.\n" * 3
        strategy = FlatSectionChunkingStrategy(section_split_threshold=300, section_overlap=30)
        chunks = strategy.chunk(text, base_metadata)

        for chunk in chunks:
            content = chunk.content
            link_start = -1
            state = "text"

            for i, char in enumerate(content):
                if state == "text":
                    if char == "[":
                        link_start = i
                        state = "link_text"
                elif state == "link_text":
                    if char == "]":
                        if i + 1 < len(content) and content[i + 1] == "(":
                            state = "link_url"
                        else:
                            raise AssertionError(
                                f"Chunk contains partial Markdown link: {content[link_start : min(link_start + 80, len(content))]}"
                            )
                elif state == "link_url" and char == ")":
                    link_start = -1
                    state = "text"

            assert state == "text", (
                f"Chunk contains partial Markdown link: {content[link_start : min(link_start + 80, len(content))]}"
            )


class TestFlatSectionChunkingStrategyHeaderlessFallback:

    @pytest.fixture
    def strategy(self):
        return FlatSectionChunkingStrategy(enable_headerless_fallback=True)

    def test_falls_back_to_h3_when_no_h2(self, strategy, base_metadata):
        text = "### Sub A\n\nContent under A.\n\n### Sub B\n\nContent under B."
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) == 2
        assert {c.metadata["section_title"] for c in chunks} == {"Sub A", "Sub B"}
        assert all(c.metadata["chunk_type"] == "flat_section" for c in chunks)

    def test_h3_fallback_preserves_preamble(self, strategy, base_metadata):
        text = "Some introductory content before headers.\n\n### Sub A\n\nContent under A.\n\n### Sub B\n\nContent under B."
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) == 3
        assert chunks[0].content == "Some introductory content before headers."
        assert chunks[0].metadata["section_title"] == "(preamble)"
        assert chunks[0].metadata["chunk_type"] == "flat_section"
        assert chunks[1].metadata["section_title"] == "Sub A"
        assert chunks[2].metadata["section_title"] == "Sub B"

    def test_structured_doc_under_limit_not_split(self, strategy, base_metadata):
        text = "## Only Section\n\nA short body well under the fallback target."
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) == 1
        assert chunks[0].metadata["chunk_type"] == "flat_section"

    def test_paragraph_fallback_triggers_for_large_headerless_doc(self, strategy, base_metadata):
        paragraphs = [f"Absatz {i}: " + "lorem ipsum dolor sit amet " * 10 for i in range(60)]
        text = "\n\n".join(paragraphs)
        assert len(text) > FlatSectionChunkingStrategy.FALLBACK_CHUNK_TARGET

        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) > 1
        assert all(c.metadata["chunk_type"] == "flat_paragraph_fallback" for c in chunks)
        assert all(len(c.content) <= FlatSectionChunkingStrategy.FALLBACK_CHUNK_TARGET for c in chunks)

    def test_paragraph_fallback_overlap_is_boundary_safe_context(self, strategy, base_metadata):
        """Each chunk's head is a boundary-safe suffix of the previous chunk (#695).

        The seeded overlap is redundant trailing context carried onto the next
        chunk's head: it is a suffix of the previous chunk, char-for-char, but —
        unlike the old raw ``chunk_text[-overlap:]`` slice — never begins
        mid-token. That raw slice cut ``ips|um`` and seeded the next chunk with
        the fragment ``um dolor …``; the fix advances the seed to ``dolor …``.
        """
        paragraphs = [f"Absatz {i}: " + "lorem ipsum dolor sit amet " * 10 for i in range(60)]
        text = "\n\n".join(paragraphs)

        chunks = strategy.chunk(text, base_metadata)
        max_overlap = FlatSectionChunkingStrategy.FALLBACK_OVERLAP

        assert len(chunks) > 1
        for i in range(len(chunks) - 1):
            prev, nxt = chunks[i].content, chunks[i + 1].content
            # Reconstruct the seeded overlap: the longest prefix of the next
            # chunk (<= FALLBACK_OVERLAP) that is a suffix of the previous chunk.
            seed_len = next(
                (k for k in range(min(len(nxt), max_overlap), 0, -1) if prev.endswith(nxt[:k])),
                0,
            )
            assert seed_len > 0, f"no overlap context carried across boundary {i}"
            seed_start = len(prev) - seed_len
            assert not starts_mid_token(prev, seed_start), (
                f"overlap seed begins mid-token: {prev[seed_start : seed_start + 30]!r}"
            )

    def test_two_near_target_paragraphs_do_not_overflow(self, strategy, base_metadata):
        """Regression: seeded overlap must not push a near-target chunk over target.

        Two paragraphs just under the target previously overflowed: flushing the
        first chunk seeded the next with FALLBACK_OVERLAP trailing chars, and
        appending the second near-target paragraph produced a chunk of
        ``para + overlap`` > FALLBACK_CHUNK_TARGET. The overlap is now trimmed so
        the bound always holds.
        """
        target = FlatSectionChunkingStrategy.FALLBACK_CHUNK_TARGET
        # Each paragraph is just under the target (target - 100), so the second
        # one plus a full overlap would exceed it.
        para = ("wort " * ((target - 100) // 5)).rstrip()
        assert target - 200 < len(para) <= target
        text = para + "\n\n" + para

        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) > 1
        assert all(len(c.content) <= target for c in chunks), (
            f"chunk sizes {[len(c.content) for c in chunks]} exceed target {target}"
        )

    def test_large_preamble_before_h3_is_split(self, strategy, base_metadata):
        """Regression: a large preamble before a trailing H3 must not be one chunk.

        It previously bypassed both split thresholds and stayed a single oversized
        chunk; it must now be paragraph-split like a headerless body.
        """
        target = FlatSectionChunkingStrategy.FALLBACK_CHUNK_TARGET
        preamble = "\n\n".join(f"Absatz {i}: " + "lorem ipsum dolor sit amet " * 10 for i in range(60))
        assert len(preamble) > target
        text = preamble + "\n\n### Sub A\n\nContent under A."

        chunks = strategy.chunk(text, base_metadata)

        preamble_chunks = [c for c in chunks if c.metadata["section_title"] == "(preamble)"]
        assert len(preamble_chunks) > 1, "Large preamble should be split into multiple chunks"
        assert all(len(c.content) <= target for c in preamble_chunks)
        assert any(c.metadata["section_title"] == "Sub A" for c in chunks)

    def test_fallback_target_is_constructor_configurable(self, base_metadata):
        strategy = FlatSectionChunkingStrategy(
            fallback_chunk_target=800, fallback_overlap=100, enable_headerless_fallback=True
        )
        paragraphs = ["Absatz " + "lorem ipsum dolor sit amet " * 8 for _ in range(20)]
        text = "\n\n".join(paragraphs)

        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) > 1
        assert all(c.metadata["chunk_type"] == "flat_paragraph_fallback" for c in chunks)
        assert all(len(c.content) <= 800 for c in chunks)

    def test_small_headerless_doc_returns_single_chunk(self, strategy, base_metadata):
        text = "Plain text, no headers, comfortably under the fallback target."
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) == 1
        assert chunks[0].content == text

    def test_single_oversized_unsplittable_paragraph_is_best_effort(self, strategy, base_metadata, caplog):
        target = FlatSectionChunkingStrategy.FALLBACK_CHUNK_TARGET
        text = "x" * (target + 500)  # no '\n' or ' ' to split on

        with caplog.at_level(logging.WARNING):
            chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) >= 1
        # No content silently dropped: every 'x' is accounted for across chunks.
        assert "".join(c.content for c in chunks).count("x") >= target + 500
        assert "character slicing" in caplog.text


class TestFlatSectionChunkingStrategyFallbackDisabledByDefault:

    @pytest.fixture
    def strategy(self):
        return FlatSectionChunkingStrategy()

    def test_h3_only_doc_is_single_chunk_when_disabled(self, strategy, base_metadata):
        text = "### Sub A\n\nContent under A.\n\n### Sub B\n\nContent under B."
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) == 1
        assert chunks[0].content == text

    def test_large_headerless_doc_is_single_chunk_when_disabled(self, strategy, base_metadata):
        paragraphs = [f"Absatz {i}: " + "lorem ipsum dolor sit amet " * 10 for i in range(60)]
        text = "\n\n".join(paragraphs)
        assert len(text) > FlatSectionChunkingStrategy.FALLBACK_CHUNK_TARGET

        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) == 1
        assert chunks[0].content == text


class TestFlatSectionChunkingStrategyMetadataEnrichment:

    @pytest.fixture
    def strategy(self):
        return FlatSectionChunkingStrategy()

    def test_has_table_true_when_table_present(self, strategy, markdown_with_table, base_metadata):
        chunks = strategy.chunk(markdown_with_table, base_metadata)
        assert chunks[0].metadata["has_table"] is True

    def test_has_table_false_when_no_table(self, strategy, markdown_with_h2_sections, base_metadata):
        chunks = strategy.chunk(markdown_with_h2_sections, base_metadata)
        assert all(c.metadata["has_table"] is False for c in chunks)

    def test_has_note_true_for_tip(self, strategy, markdown_with_tip_note, base_metadata):
        chunks = strategy.chunk(markdown_with_tip_note, base_metadata)
        assert chunks[0].metadata["has_note"] is True

    def test_note_types_includes_tip(self, strategy, markdown_with_tip_note, base_metadata):
        chunks = strategy.chunk(markdown_with_tip_note, base_metadata)
        assert "tip" in chunks[0].metadata["note_types"]

    def test_note_types_includes_important(self, strategy, markdown_with_important_note, base_metadata):
        chunks = strategy.chunk(markdown_with_important_note, base_metadata)
        assert "important" in chunks[0].metadata["note_types"]

    def test_no_note_types_when_no_notes(self, strategy, markdown_with_h2_sections, base_metadata):
        chunks = strategy.chunk(markdown_with_h2_sections, base_metadata)
        assert all("note_types" not in c.metadata for c in chunks)


class TestFlatSectionChunkingStrategyExtractSections:

    @pytest.fixture
    def strategy(self):
        return FlatSectionChunkingStrategy()

    def test_extracts_h2_sections(self, strategy):
        text = "## One\n\nContent 1\n\n## Two\n\nContent 2"
        sections = strategy._extract_sections(text, level=2)
        assert len(sections) == 2
        assert sections[0].metadata["title"] == "One"
        assert sections[1].metadata["title"] == "Two"

    def test_extracts_h3_sections(self, strategy):
        text = "### Sub One\n\nContent 1\n\n### Sub Two\n\nContent 2"
        sections = strategy._extract_sections(text, level=3)
        assert len(sections) == 2
        assert sections[0].metadata["title"] == "Sub One"

    def test_returns_empty_list_for_no_sections(self, strategy):
        sections = strategy._extract_sections("Plain text only", level=2)
        assert sections == []

    def test_section_content_includes_header(self, strategy):
        text = "## Title\n\nBody text"
        sections = strategy._extract_sections(text, level=2)
        assert sections[0].content.startswith("## Title")


class TestParagraphClusteringBoundaries:

    @pytest.fixture
    def strategy(self):
        return FlatSectionChunkingStrategy(
            fallback_chunk_target=200,
            fallback_overlap=40,
            enable_headerless_fallback=True,
        )

    def test_lead_in_is_carried_to_the_chunk_holding_its_list(self, strategy):
        filler = "\n\n".join(f"Absatz {i} mit ausreichend Text für die Zielgröße." for i in range(1, 6))
        lead_in = "Leistungen werden nicht erbracht, wenn Sie"
        text = f"{filler}\n\n{lead_in}\n\n- wegen eines Arbeitsunfalls Anspruch haben,\n\n- oder aus anderem Grund."
        chunks = strategy._cluster_paragraphs(text)
        for chunk in chunks:
            if lead_in in chunk:
                assert "- wegen eines Arbeitsunfalls" in chunk, f"lead-in orphaned: {chunk!r}"

    def test_numbered_heading_is_not_orphaned(self, strategy):
        filler = "\n\n".join(f"Absatz {i} mit ausreichend Text für die Zielgröße." for i in range(1, 6))
        text = f"{filler}\n\n3.4 Leistungen zur Prävention\n\nDiese Leistungen dienen der Vorbeugung."
        chunks = strategy._cluster_paragraphs(text)
        for chunk in chunks:
            last = [line for line in chunk.split("\n") if line.strip()][-1].strip()
            assert last != "3.4 Leistungen zur Prävention", f"heading orphaned: {chunk!r}"

    def test_chunks_still_respect_the_target(self, strategy):
        paragraphs = [f"Absatz {i} mit etwas Text zur Rentenversicherung." for i in range(1, 30)]
        text = "\n\n".join(paragraphs) + "\n\nEinleitung:\n\n- erster Punkt\n\n- zweiter Punkt"
        chunks = strategy._cluster_paragraphs(text)
        assert all(len(chunk) <= strategy.fallback_chunk_target for chunk in chunks)

    def test_no_content_is_lost(self, strategy):
        paragraphs = [f"Absatz {i} zur Rentenversicherung." for i in range(1, 20)]
        text = "\n\n".join(paragraphs)
        chunks = strategy._cluster_paragraphs(text)
        joined = "\n\n".join(chunks)
        for para in paragraphs:
            assert para in joined

    def test_oversized_paragraph_is_split_on_sentence_ends(self, strategy):
        sentences = [f"Dies ist Satz Nummer {i} mit etwas mehr Text darin." for i in range(1, 15)]
        pieces = strategy._split_oversized_paragraph(" ".join(sentences))
        assert len(pieces) > 1
        for piece in pieces[:-1]:
            assert piece.rstrip().endswith("."), f"piece ends mid-sentence: {piece!r}"

    def test_boundary_safe_overlap_advances_past_a_mid_token_seed(self, strategy):
        """The reported G0103 shape: a raw overlap slice cutting 'Bet|reuung' advances to 'folgt' (#695).

        ``chunk_text[-12:]`` here is ``'reuung folgt'`` (mid-token, the exact
        reported fragment). ``_boundary_safe_overlap`` must advance the seed
        start forward to the next whole token, dropping only redundant context.
        """
        chunk_text = "Vorheriger Absatz zur Betreuung folgt"
        assert chunk_text[-12:] == "reuung folgt"  # the raw slice would seed "reuung ..."

        overlap = strategy._boundary_safe_overlap(chunk_text, max_overlap=12)

        assert overlap == "folgt"
        assert not overlap.startswith("reuung")

    def test_boundary_safe_overlap_is_a_clean_suffix_when_slice_is_aligned(self, strategy):
        chunk_text = "Erster Absatz Zweiter folgt hier"
        overlap = strategy._boundary_safe_overlap(chunk_text, max_overlap=10)
        assert overlap == "folgt hier"  # exactly the last 10 chars; nothing advanced

    def test_fallback_chunks_never_begin_mid_token(self, strategy):
        """No paragraph-fallback chunk opens on a word fragment (#695 fragment #5).

        Headerless-PDF bodies previously seeded each chunk with a raw
        ``chunk_text[-fallback_overlap:]`` slice that cut a word head — 109 of the
        live findings (``reuung``/``rsicherungsträger``/``onen``…). A boundaryless
        body built from a known vocab (incl. the reported ``Betreuung``) forces
        that char-overlap seed path; every emitted chunk must open on a complete
        vocab token.
        """
        reported = ("Betreuung", "berufsunfähig", "Rentenversicherungsträger", "Informationen", "Datenschutz")
        vocab = set(reported) | {f"Wort{i:03d}" for i in range(120)}
        body = " ".join(f"Wort{i:03d} {reported[i % len(reported)]}" for i in range(120))
        assert "." not in body and "\n" not in body  # force the char-overlap seed path

        chunks = strategy._cluster_paragraphs(body)

        assert len(chunks) > 1
        for chunk in chunks:
            first_token = chunk.split(maxsplit=1)[0]
            assert first_token in vocab, f"paragraph-fallback chunk begins mid-token: {chunk[:40]!r}"
        assert not any(chunk.lstrip().startswith("reuung") for chunk in chunks)
        assert any("Betreuung" in chunk for chunk in chunks)


class TestFlatSectionTableAtomicity:

    def test_parent_section_split_keeps_table_atomic(self, base_metadata):
        prose = "Dies ist ein Satz zur Rentenversicherung. " * 20
        table = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
        text = f"## Section\n\n{prose}\n\n{table}\n\n{prose}"
        strategy = FlatSectionChunkingStrategy(section_split_threshold=500, section_overlap=50)

        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) > 1
        assert sum(table in c.content for c in chunks) == 1, "table must appear intact in exactly one chunk"
        assert not any(_starts_with_headerless_row(c.content) for c in chunks)

    def test_standalone_small_table_is_single_chunk(self, base_metadata):
        strategy = FlatSectionChunkingStrategy()  # XML path: headerless fallback disabled
        text = "# Titel\n\nLead-in text.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"

        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) == 1
        assert chunks[0].content == text

    def test_standalone_table_free_doc_has_no_continuation(self, base_metadata):
        strategy = FlatSectionChunkingStrategy()
        text = "# Titel\n\n" + ("Ein Absatz ganz ohne Tabelle. " * 300)

        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) == 1
        assert chunks[0].content == text

    def test_standalone_oversized_table_splits_with_repeated_header(self, base_metadata):
        header = "| Jahr | Beitrag |"
        separator = "| --- | --- |"
        rows = [f"| {2000 + i} | {i},6 Prozent |" for i in range(300)]
        table = f"{header}\n{separator}\n" + "\n".join(rows)
        head = "# Beitragssätze\n\nDie folgende Tabelle zeigt die Werte:"
        text = f"{head}\n\n{table}"
        assert len(table) > 2500
        strategy = FlatSectionChunkingStrategy()  # no H2, fallback disabled
        metadata = {"chunk_type": "table", "source": "B01_table_000"}

        chunks = strategy.chunk(text, metadata)

        assert len(chunks) > 1
        # Head (title + lead-in) stays on the first piece.
        assert chunks[0].content.startswith("# Beitragssätze")
        assert f"{header}\n{separator}" in chunks[0].content
        assert "table_continuation" not in chunks[0].metadata
        # Continuation pieces repeat the header/separator and are flagged.
        for cont in chunks[1:]:
            assert cont.content.startswith(f"{header}\n{separator}")
            assert cont.metadata["table_continuation"] is True
            assert len(cont.content) <= strategy.section_split_threshold
        # chunk_type is inherited on every piece; no row is lost.
        assert all(c.metadata["chunk_type"] == "table" for c in chunks)
        joined = "\n".join(c.content for c in chunks)
        for row in rows:
            assert row in joined

    def test_pdf_headerless_oversized_table_is_continued(self, base_metadata):
        header = "| Spalte 1 | Spalte 2 |"
        separator = "| --- | --- |"
        rows = [f"| Wert {i} in Zeile | {i * 3} Euro |" for i in range(300)]
        table = f"{header}\n{separator}\n" + "\n".join(rows)
        strategy = FlatSectionChunkingStrategy(enable_headerless_fallback=True)

        pieces = strategy._split_oversized_paragraph(table)

        assert len(pieces) > 1
        for piece in pieces:
            assert piece.startswith(f"{header}\n{separator}")
            assert not _starts_with_headerless_row(piece)


class TestFlatSectionChunkingStrategyStartBoundaries:

    def test_split_sub_chunks_never_begin_mid_token(self, base_metadata):
        words = ["Rentenversicherungsträger", "berufsunfähig", "Informationen"]
        vocab = set(words) | {f"Wort{i:03d}" for i in range(120)}
        body = " ".join(f"Wort{i:03d} {words[i % 3]}" for i in range(120))
        text = "## Abschnitt\n\n" + body
        assert "." not in body

        strategy = FlatSectionChunkingStrategy(section_split_threshold=200, section_overlap=60)
        chunks = strategy.chunk(text, base_metadata)

        assert len(chunks) > 1
        assert all(c.metadata["chunk_type"] == "flat_section_split" for c in chunks)
        for chunk in chunks[1:]:
            first_token = chunk.content.split(maxsplit=1)[0]
            assert first_token in vocab, f"sub-chunk begins mid-token: {chunk.content[:40]!r}"
