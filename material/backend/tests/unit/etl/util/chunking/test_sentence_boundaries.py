
from etl.util.chunking.sentence_boundaries import (
    is_sentence_end,
    last_sentence_end,
    pack_by_sentences,
    split_sentences,
)


class TestIsSentenceEnd:

    def test_plain_sentence_end(self):
        text = "Das ist ein Satz. Und noch einer."
        assert is_sentence_end(text, text.index(". Und"))

    def test_abbreviation_z_b_is_not_a_boundary(self):
        text = "Das gilt z. B. für Versicherte in Deutschland."
        # the period after "B"
        assert not is_sentence_end(text, text.index("B.") + 1)

    def test_abbreviation_nr_is_not_a_boundary(self):
        text = "Die Nr. 5 der Anlage regelt das."
        assert not is_sentence_end(text, text.index("Nr.") + 2)

    def test_spaced_abbreviation_first_element_is_not_a_boundary(self):
        text = "Das gilt z. B. für alle."
        assert not is_sentence_end(text, text.index("z.") + 1)

    def test_ordinal_date_is_not_a_boundary(self):
        text = "Ab dem 1. Januar 2026 gilt der neue Wert."
        assert not is_sentence_end(text, text.index("1.") + 1)

    def test_edition_ordinal_is_not_a_boundary(self):
        text = "Siehe 20. Auflage der Broschüre."
        assert not is_sentence_end(text, text.index("20.") + 2)

    def test_lowercase_continuation_is_not_a_boundary(self):
        text = "Der Betrag von 1.500 euro ist gemeint."
        assert not is_sentence_end(text, text.index("1.") + 1)

    def test_newline_after_period_is_a_boundary(self):
        text = "Ende des Absatzes.\nNeuer Absatz."
        assert is_sentence_end(text, text.index(".\n"))

    def test_question_mark_is_a_boundary(self):
        text = "Wer zahlt das? Die Rentenversicherung."
        assert is_sentence_end(text, text.index("?"))


class TestLastSentenceEnd:

    def test_returns_index_after_final_punctuation(self):
        text = "Erster Satz. Zweiter Satz. Dritter"
        index = last_sentence_end(text, 0, len(text))
        assert index is not None
        assert text[:index].endswith("Zweiter Satz.")

    def test_returns_none_when_only_abbreviations_present(self):
        text = "Das gilt z. B. für Nr. 5 und Nr. 7 in Abs. 2 der"
        assert last_sentence_end(text, 0, len(text)) is None

    def test_respects_window_bounds(self):
        text = "Satz eins. Satz zwei. Rest"
        index = last_sentence_end(text, 0, text.index("Satz zwei"))
        assert index is not None
        assert text[:index].endswith("Satz eins.")


class TestSplitSentences:

    def test_roundtrip_preserves_text(self):
        text = "Erster Satz. Zweiter Satz? Dritter Satz! Rest ohne Ende"
        assert "".join(split_sentences(text)) == text

    def test_abbreviations_do_not_create_extra_spans(self):
        text = "Das gilt z. B. für Nr. 5 der Anlage. Danach folgt der zweite Satz."
        spans = split_sentences(text)
        assert len(spans) == 2
        assert spans[0].strip().endswith("der Anlage.")

    def test_sentence_ending_in_a_numeral_is_conservatively_merged(self):
        """A period after a digit is never a boundary — ordinals and decimals win.

        The cost is a missed boundary after "… im Jahr 2026.", which only makes a
        cut less elegant; the benefit is never splitting "1. Januar" or "Nr. 5".
        """
        text = "Der Wert gilt ab 2026. Danach wird er angepasst."
        assert len(split_sentences(text)) == 1


class TestPackBySentences:

    def test_returns_none_for_single_sentence(self):
        assert pack_by_sentences("Nur ein Satz ohne weiteres.", target=10) is None

    def test_pieces_end_on_sentence_boundaries(self):
        text = " ".join(f"Dies ist Satz Nummer {i} mit etwas Text." for i in range(1, 21))
        pieces = pack_by_sentences(text, target=120)
        assert pieces is not None
        assert len(pieces) > 1
        for piece in pieces:
            assert piece.endswith(".")

    def test_oversized_single_sentence_is_emitted_whole(self):
        long_sentence = "Wort " * 100 + "Ende."
        text = "Kurz. " + long_sentence
        pieces = pack_by_sentences(text, target=50)
        assert pieces is not None
        assert any(len(piece) > 50 for piece in pieces)
