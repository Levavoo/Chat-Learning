
from pathlib import Path

import pytest

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.convert_to_html import dita_to_html
from etl.transform.convert_to_md import text_to_md
from etl.transform.page_references import (
    EMPTY_PAGE_REF_RE,
    PAGE_CUE_RE,
    PARTIAL_PAGE_REF_RE,
    PageReferenceRewriter,
    heading_title,
    local_element_id,
)
from etl.util.parsing.dita import DitaNode, DitaNodeType, DitaParser

# A section whose title is a valid Tier 1 / chapter-ref target, plus a paragraph
# target (heading_title -> None -> Tier 2 / drop). Referenced by "#T/sec1" and
# "#T/par1"; the topic-qualified form exercises the split fixed by Component A.
_TARGETS = (
    '<section id="sec1"><title>Wie Renten besteuert werden</title><p>Inhalt.</p></section>'
    '<p id="par1">Ein erklärender Absatz.</p>'
)


def _wrap(paragraph: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<topic id="T"><title>Doc</title><body>'
        f"{paragraph}{_TARGETS}"
        "</body></topic>"
    )


def _to_html(paragraph: str) -> str:
    item = PipelineItem(
        name="doc",
        data_object=DataObject(name="doc", data=_wrap(paragraph), data_type=DataType.XML, metadata={"name": "doc"}),
    )
    return str(dita_to_html().apply(item)[0].data_object.data)


def _paragraph_text(html: str, marker: str) -> str:
    for block in html.split("<p>"):
        if marker in block:
            return block.split("</p>")[0]
    raise AssertionError(f"no <p> containing {marker!r} in:\n{html}")


class TestLocalElementId:

    @pytest.mark.parametrize(
        "href, expected",
        [
            ("#B19-20-w298a/drv-ec7792da-1234", "drv-ec7792da-1234"),
            ("#test-section", "test-section"),
            ("#a/b/c", "c"),
            ("other-topic.dita", None),
            ("", None),
        ],
    )
    def test_local_element_id(self, href, expected):
        assert local_element_id(href) == expected


class TestHeadingTitle:

    def test_section_returns_title_child(self):
        section = DitaNode(
            node_type=DitaNodeType.SECTION,
            children=[
                DitaNode(node_type=DitaNodeType.TITLE, text="Kapiteltitel"),
                DitaNode(node_type=DitaNodeType.PARAGRAPH, text="Rumpf"),
            ],
        )
        assert heading_title(section) == "Kapiteltitel"

    def test_title_returns_own_text(self):
        assert heading_title(DitaNode(node_type=DitaNodeType.TITLE, text="Ein Titel")) == "Ein Titel"

    def test_paragraph_returns_none(self):
        assert heading_title(DitaNode(node_type=DitaNodeType.PARAGRAPH, text="Fließtext")) is None

    def test_subheading_returns_none(self):
        assert heading_title(DitaNode(node_type=DitaNodeType.SUBHEADING, text="Zwischenüberschrift")) is None

    def test_section_without_title_returns_none(self):
        section = DitaNode(
            node_type=DitaNodeType.SECTION, children=[DitaNode(node_type=DitaNodeType.PARAGRAPH, text="x")]
        )
        assert heading_title(section) is None

    def test_none_returns_none(self):
        assert heading_title(None) is None


class TestEmptyPageRefDetector:

    @pytest.mark.parametrize(
        "text",
        [
            "Mehr dazu ab Seite .",
            "lesen Sie auf den Seiten und .",
            "finden Sie auf den Seiten bis .",
            "auf den Seiten, .",
            "finden Sie auf den Seiten\u00a0und\u00a0.",
            "erheblich gemindert (siehe Seite ).",
        ],
    )
    def test_matches_empty_page_ref(self, text):
        assert EMPTY_PAGE_REF_RE.search(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            # real numbered references (a digit breaks the run)
            "Mehr dazu ab Seite 12.",
            "siehe Seite 4 und 5.",
            # legitimate prose that merely contains "Seite"/"Seiten"
            "Auf dieser Seite finden Sie alles.",
            "als Begleiter an Ihrer Seite.",
            "Besuchen Sie unsere Startseite.",
            "Infos auf unserer Internetseite, dort mehr.",
            "1,45 Millionen Schulhefte (32 Seiten).",
            "Alles auf der folgenden Seite.",
        ],
    )
    def test_ignores_real_or_harmless_text(self, text):
        assert EMPTY_PAGE_REF_RE.search(text) is None


class TestPartialPageRefDetector:
    """PARTIAL_PAGE_REF_RE flags empty/partial refs the precise detector misses.

    A und/bis/, connector sitting directly against a page-cued "Seite(n)" always
    means the left page number was dropped; a valid reference never does that.
    """

    @pytest.mark.parametrize(
        "text",
        [
            # missing-left + real-right (a lone surviving number)
            "Die Anschriften finden Sie auf den Seiten\u00a0 und 30.",
            "Näheres finden Sie auf den Seiten bis 30.",
            # no-number range/multiple lead-in fronting a clause
            "Auf den Seiten\u00a0 bis haben wir alle Anschriften.",
            "erhältlich. Auf den Seiten bis  haben wir alles zusammengestellt.",
            # empty forms are also caught by the broad probe
            "lesen Sie auf den Seiten und .",
            "finden Sie auf den Seiten, .",
        ],
    )
    def test_matches_empty_or_partial(self, text):
        assert PARTIAL_PAGE_REF_RE.search(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            # complete references — a number binds directly to "Seite(n)"
            "auf Seite 1 die persönlichen Daten",
            "auf den Seiten 12 und 30.",
            "auf den Seiten 12 bis 15.",
            "Mehr dazu ab Seite 12.",
            # titled / URL references — no connector against "Seite(n)"
            'auf den Seiten "Checkliste: Wann" und "X" gibt Orientierung.',
            "auf der Seite [www.deutsche-rentenversicherung.de] mehr.",
            # bibliographic page count: number before "Seiten", no cue
            "1. Auflage 2019, 512 Seiten, Schutzgebühr 5 Euro.",
            # harmless prose
            "als Begleiter an Ihrer Seite, jederzeit.",
        ],
    )
    def test_ignores_valid_or_harmless_text(self, text):
        assert PARTIAL_PAGE_REF_RE.search(text) is None


class TestPageReferenceRewrite:

    def test_singular_tier1_section_title(self):
        html = _to_html('<p>Mehr zum „Rentenfreibetrag“ ab Seite <xref scope="local" href="#T/sec1"/>.</p>')
        assert "Mehr zum „Rentenfreibetrag“ im Abschnitt „Wie Renten besteuert werden“." in html
        assert EMPTY_PAGE_REF_RE.search(_paragraph_text(html, "Rentenfreibetrag")) is None

    def test_singular_tier2_paragraph_target(self):
        html = _to_html(
            '<p>Mehr zur Ertragsanteilsbesteuerung lesen Sie ab Seite <xref scope="local" href="#T/par1"/>.</p>'
        )
        assert "Mehr zur Ertragsanteilsbesteuerung lesen Sie." in html

    def test_multiple_und_unresolved_tier2(self):
        html = _to_html(
            "<p>Welche das sind, lesen Sie auf den Seiten "
            '<xref scope="local" href="#T/par1"/> und <xref scope="local" href="#T/par1"/>.</p>'
        )
        assert "Welche das sind, lesen Sie." in html
        assert "Seiten" not in _paragraph_text(html, "Welche das sind")

    def test_range_bis_tier2(self):
        html = _to_html(
            "<p>Weitere Informationen finden Sie auf den Seiten "
            '<xref scope="local" href="#T/par1"/> bis <xref scope="local" href="#T/par1"/>.</p>'
        )
        assert "Weitere Informationen finden Sie." in html

    def test_range_bis_tier1_section_titles(self):
        html = _to_html(
            "<p>Details finden Sie auf den Seiten "
            '<xref scope="local" href="#T/sec1"/> bis <xref scope="local" href="#T/sec1"/>.</p>'
        )
        assert (
            "Details finden Sie in den Abschnitten "
            "„Wie Renten besteuert werden“ bis „Wie Renten besteuert werden“." in html
        )

    def test_multiple_und_tier1_section_titles(self):
        html = _to_html(
            "<p>Beachten Sie die Seiten "
            '<xref scope="local" href="#T/sec1"/> und <xref scope="local" href="#T/sec1"/>.</p>'
        )
        assert (
            "Beachten Sie in den Abschnitten „Wie Renten besteuert werden“ und „Wie Renten besteuert werden“." in html
        )

    def test_parenthetical_removed_with_empty_parens(self):
        html = _to_html('<p>Die Rente wird erheblich gemindert (siehe Seite <xref scope="local" href="#T/par1"/>).</p>')
        assert "Die Rente wird erheblich gemindert." in html
        assert "()" not in _paragraph_text(html, "gemindert")

    def test_chapter_reference_restored(self):
        html = _to_html('<p>Lesen Sie hierzu bitte unser Kapitel „<xref scope="local" href="#T/sec1"/>“.</p>')
        assert "Lesen Sie hierzu bitte unser Kapitel „Wie Renten besteuert werden“." in html

    def test_literal_title_kept_when_trailing_page_ref_removed(self):
        html = _to_html(
            "<p>Details finden Sie im Kapitel „Rehabilitation für Angehörige“ auf Seite "
            '<xref scope="local" href="#T/par1"/>.</p>'
        )
        assert "Details finden Sie im Kapitel „Rehabilitation für Angehörige“." in html

    def test_mixed_multi_locution(self):
        html = _to_html(
            "<p>Wenn Sie mehr wissen möchten, lesen Sie bitte auch die Seiten "
            '<xref scope="local" href="#T/par1"/> und <xref scope="local" href="#T/par1"/>, '
            'über Kinderrehabilitation Seite <xref scope="local" href="#T/par1"/>.</p>'
        )
        assert "Wenn Sie mehr wissen möchten, lesen Sie bitte auch, über Kinderrehabilitation." in html
        assert EMPTY_PAGE_REF_RE.search(_paragraph_text(html, "Kinderrehabilitation")) is None

    def test_non_breaking_space_variant(self):
        html = _to_html(
            "<p>Die Anschriften finden Sie auf den Seiten "
            '<xref scope="local" href="#T/par1"/>\u00a0und\u00a0<xref scope="local" href="#T/par1"/>.</p>'
        )
        assert "Die Anschriften finden Sie." in html

    def test_subdoc_unresolved_chapter_ref_drops_empty_quotes(self):
        html = _to_html('<p>Lesen Sie unser Kapitel „<xref scope="local" href="#T/not-here"/>“.</p>')
        text = _paragraph_text(html, "Lesen Sie unser Kapitel")
        assert "Lesen Sie unser Kapitel." in html
        assert "„" not in text and "“" not in text

    def test_external_xref_left_untouched(self):
        html = _to_html('<p>Mehr dazu auf Seite <xref href="https://example.org" scope="external">Portal</xref>.</p>')
        assert "<a href='https://example.org'>Portal</a>" in html


class TestSingularRangeMultiReferenceRegression:

    # --- Singular ---------------------------------------------------------
    def test_singular_tier1_single_titled_reference(self):
        html = _to_html('<p>Hinweise dazu ab Seite <xref scope="local" href="#T/sec1"/>.</p>')
        text = _paragraph_text(html, "Hinweise dazu")
        assert "Hinweise dazu im Abschnitt „Wie Renten besteuert werden“." in text
        assert " und " not in text and " bis " not in text

    def test_singular_tier2_locution_removed(self):
        html = _to_html('<p>Hinweise dazu ab Seite <xref scope="local" href="#T/par1"/>.</p>')
        text = _paragraph_text(html, "Hinweise dazu")
        assert "Hinweise dazu." in text
        assert EMPTY_PAGE_REF_RE.search(text) is None

    # --- Range ("bis") ----------------------------------------------------
    def test_range_bis_tier1_joins_titles_with_bis(self):
        html = _to_html(
            "<p>Näheres finden Sie auf den Seiten "
            '<xref scope="local" href="#T/sec1"/> bis <xref scope="local" href="#T/sec1"/>.</p>'
        )
        text = _paragraph_text(html, "Näheres")
        assert "in den Abschnitten „Wie Renten besteuert werden“ bis „Wie Renten besteuert werden“." in text
        assert " und " not in text

    def test_range_bis_tier2_span_removed(self):
        html = _to_html(
            "<p>Näheres finden Sie auf den Seiten "
            '<xref scope="local" href="#T/par1"/> bis <xref scope="local" href="#T/par1"/>.</p>'
        )
        text = _paragraph_text(html, "Näheres")
        assert "Näheres finden Sie." in text
        assert "Seiten" not in text

    # --- Multiple ("und") -------------------------------------------------
    def test_multiple_und_tier1_joins_titles_with_und(self):
        html = _to_html(
            "<p>Bitte beachten Sie die Seiten "
            '<xref scope="local" href="#T/sec1"/> und <xref scope="local" href="#T/sec1"/>.</p>'
        )
        text = _paragraph_text(html, "Bitte beachten")
        assert (
            "Bitte beachten Sie in den Abschnitten "
            "„Wie Renten besteuert werden“ und „Wie Renten besteuert werden“." in text
        )
        assert " bis " not in text

    def test_multiple_und_three_targets_tier1(self):
        html = _to_html(
            "<p>Bitte beachten Sie die Seiten "
            '<xref scope="local" href="#T/sec1"/> und <xref scope="local" href="#T/sec1"/> '
            'und <xref scope="local" href="#T/sec1"/>.</p>'
        )
        text = _paragraph_text(html, "Bitte beachten")
        assert text.count("„Wie Renten besteuert werden“") == 3
        assert " bis " not in text
        assert EMPTY_PAGE_REF_RE.search(text) is None

    def test_multiple_und_tier2_span_removed(self):
        html = _to_html(
            "<p>Weitere Hinweise stehen auf den Seiten "
            '<xref scope="local" href="#T/par1"/> und <xref scope="local" href="#T/par1"/>.</p>'
        )
        text = _paragraph_text(html, "Weitere Hinweise")
        assert "Weitere Hinweise stehen." in text
        assert "Seiten" not in text


class TestPageCueWordIntegrity:
    """Regression: the page cue must never truncate a real word (#693 review 🔴).

    ``PAGE_CUE_RE`` is anchored at the end of the preceding text and then
    substituted out. Without word boundaries the cue/article/``Seite`` tokens
    match *inside* a preceding word (``Internetseite``, ``jeder``, ``Ablauf``),
    silently mangling it — the exact broken-prose failure mode #693 exists to
    eliminate. Neither corpus scan can catch this (a mangled word leaves no
    surviving xref and no ``EMPTY_PAGE_REF_RE`` match), so it is guarded here.
    """

    def test_compound_word_ending_in_seite_not_mangled(self):
        # "Internetseite" ends in "seite"; an unanchored cue would delete "seite".
        html = _to_html('<p>Besuchen Sie unsere Internetseite <xref scope="local" href="#T/par1"/>.</p>')
        text = _paragraph_text(html, "Besuchen Sie")
        assert "Internetseite" in text
        assert "Internet." not in text

    def test_compound_word_ending_in_seite_not_turned_into_abschnitt(self):
        # With a resolvable section target the old bug produced "Internet im Abschnitt …".
        html = _to_html('<p>Besuchen Sie unsere Internetseite <xref scope="local" href="#T/sec1"/>.</p>')
        text = _paragraph_text(html, "Besuchen Sie")
        assert "Internetseite" in text
        assert "Internet im Abschnitt" not in text

    def test_word_with_article_syllable_not_split(self):
        # "jeder" ends in "der"; an unanchored article match would leave "auf je".
        html = _to_html('<p>Das gilt auf jeder Seite <xref scope="local" href="#T/par1"/>.</p>')
        text = _paragraph_text(html, "Das gilt")
        assert "auf jeder" in text
        assert "auf je." not in text

    def test_word_ending_in_prefix_syllable_not_split(self):
        # "Ablauf" ends in "auf"; the prefix alternative must not match inside it.
        html = _to_html('<p>Der Ablauf Seite <xref scope="local" href="#T/par1"/> ist wichtig.</p>')
        text = _paragraph_text(html, "Der Ablauf")
        assert "Ablauf" in text
        assert "Der Abl " not in text and "Der Abl." not in text


class TestMixedConnectorTier1:

    def test_mixed_und_bis_uses_per_connector_wording(self):
        html = _to_html(
            "<p>Details finden Sie auf den Seiten "
            '<xref scope="local" href="#T/sec1"/> und <xref scope="local" href="#T/sec1"/> '
            'bis <xref scope="local" href="#T/sec1"/>.</p>'
        )
        text = _paragraph_text(html, "Details finden Sie")
        title = "„Wie Renten besteuert werden“"
        assert f"in den Abschnitten {title} und {title} bis {title}." in text
        # the old all-"bis" behaviour would emit "… bis … bis …" with no "und".
        assert " und " in text


class TestPageReferenceRewriteMarkdown:

    def _to_md(self, paragraph: str) -> str:
        item = PipelineItem(
            name="doc",
            data_object=DataObject(name="doc", data=_wrap(paragraph), data_type=DataType.XML, metadata={"name": "doc"}),
        )
        html_item = dita_to_html().apply(item)[0]
        return str(text_to_md().apply(html_item)[0].data_object.data)

    def test_tier2_prose_in_markdown(self):
        md = self._to_md(
            '<p>Welche das sind, lesen Sie auf den Seiten <xref scope="local" href="#T/par1"/> und <xref scope="local" href="#T/par1"/>.</p>'
        )
        assert "Welche das sind, lesen Sie." in md
        assert EMPTY_PAGE_REF_RE.search(md) is None

    def test_chapter_ref_in_markdown(self):
        md = self._to_md('<p>Lesen Sie hierzu bitte unser Kapitel „<xref scope="local" href="#T/sec1"/>“.</p>')
        assert "Lesen Sie hierzu bitte unser Kapitel „Wie Renten besteuert werden“." in md


_clean = PageReferenceRewriter._clean_literal_text


class TestLiteralPlaceholderRewrite:
    """Xref-less literal page-number placeholders — the #693 residual forms.

    The print pipeline drops the page number, leaving prose such as ``… ab
    Seite .`` with **no** ``<xref>`` to key off, so :class:`PageReferenceRewriter`
    could not previously reach them. :meth:`PageReferenceRewriter._clean_literal_text`
    excises the whole reference span (cue → ``Seite(n)`` → empty ``und``/``bis``/
    ``,`` connectors) and re-normalises. Every residual form observed in the
    seed-data corpus is locked here; expected outputs were computed from the
    implementation and asserted grammatical.
    """

    @pytest.mark.parametrize(
        "text, expected",
        [
            # --- singular (terminal punctuation) ---
            ("Die Kontaktdaten finden Sie ab Seite .", "Die Kontaktdaten finden Sie."),
            ("beraten. Adressen finden Sie ab Seite .)", "beraten. Adressen finden Sie.)"),
            ("nehmen.(Lesen Sie auch ab Seite .)", "nehmen.(Lesen Sie auch.)"),
            ("Lesen Sie ab Seite , wie Sie uns erreichen.", "Lesen Sie, wie Sie uns erreichen."),
            ("Rentenversicherung“ ab Seite .", "Rentenversicherung“."),
            # double preposition "auf ab" (source data quirk, #204)
            ("Die Anschrift finden Sie auf ab Seite .", "Die Anschrift finden Sie."),
            # --- range ("bis") ---
            ("Ansprechpartner finden Sie auf den Seiten  bis .", "Ansprechpartner finden Sie."),
            ("Rentenversicherung (siehe Seite  bis ).", "Rentenversicherung."),
            # --- multiple ("und") ---
            ("Die Anschriften finden Sie auf den Seiten  und .", "Die Anschriften finden Sie."),
            ("brauchen.(Die Anschriften finden Sie auf den Seiten  und .)", "brauchen.(Die Anschriften finden Sie.)"),
            # --- empty chapter label + trailing range (#111) ---
            ("finden Sie im Kapitel „“ auf den Seiten  bis .", "finden Sie im Kapitel."),
            # --- "siehe auch" cue variant (#401) ---
            ("an Ihre Rentenversicherung, siehe auch Seite .)", "an Ihre Rentenversicherung.)"),
            # --- whitespace variants: U+00A0 and newline in the cue/slot ---
            ("Die Anschriften finden Sie auf den Seiten\u00a0 und\u00a0.", "Die Anschriften finden Sie."),
            ("Ansprechpartner finden Sie auf den\n            Seiten\u00a0 bis .", "Ansprechpartner finden Sie."),
            # --- mid-sentence resumption (no terminal punctuation, #109/#501/#400/#112) ---
            ("Rentenversicherung“ ab Seite  finden Sie alle Infos.", "Rentenversicherung“ finden Sie alle Infos."),
            ("Rentenversicherung“ ab Seite  oder online.", "Rentenversicherung“ oder online."),
            ("auch bei den auf den Seiten  bis  genannten Stellen an.", "auch bei den genannten Stellen an."),
            (
                "finden Sie im Serviceteil auf den Seiten  bis . Gern nennen wir",
                "finden Sie im Serviceteil. Gern nennen wir",
            ),
        ],
    )
    def test_literal_placeholder_forms(self, text: str, expected: str):
        result = _clean(text)
        assert result == expected
        assert EMPTY_PAGE_REF_RE.search(result) is None


class TestLiteralPlaceholderExclusions:

    @pytest.mark.parametrize(
        "text",
        [
            # a complete range/multiple reference (both page numbers present).
            "Die Anschriften finden Sie auf den Seiten 12 und 30.",
            "Näheres finden Sie auf den Seiten 12 bis 15.",
            "Mehr dazu ab Seite 12.",
            "siehe Seite 4 und 5.",
            # idioms — no page-number cue, or "ab" is a verb particle after "Seite".
            "als Begleiter an Ihrer Seite.",
            "Er steht Ihnen zur Seite.",
            "hängt nicht von dritter Seite ab.",
            "profitieren beide Seiten von der Regelung.",
            # a described page: the adjective breaks the article→Seite adjacency.
            "auf der nächsten Seite die Adressen.",
            "erhalten Sie auf den folgenden Seiten.",
            "die erste Seite Ihres Rentenbescheides.",
            # a page count.
            "1,45 Millionen Schulhefte (32 Seiten).",
            # a titled reference (literal quotes mark the target).
            'Die Checkliste auf den Seiten "Checkliste: Wann" und "X" gibt Orientierung.',
        ],
    )
    def test_valid_prose_unchanged(self, text: str):
        assert _clean(text) == text


class TestPartialPlaceholderRepair:
    """Partial (not merely empty) placeholders repaired to grammatical German (#693).

    A surviving token hides the dropped page number, so the empty-placeholder
    pass skips these; the two dedicated repairs turn them into valid prose.
    """

    @pytest.mark.parametrize(
        "text, expected",
        [
            # missing-left + real-right → grammatical singular "<cue> Seite <n>"
            ("Die Anschriften finden Sie auf den Seiten\u00a0 und 30.", "Die Anschriften finden Sie auf Seite 30."),
            ("Näheres finden Sie auf den Seiten bis 30.", "Näheres finden Sie auf Seite 30."),
            ("Infos auf den Seiten , 30.", "Infos auf Seite 30."),
            # cue preposition is preserved, article dropped
            ("siehe Seiten und 30", "siehe Seite 30"),
            (
                "brauchen.(Die Anschriften finden Sie auf den Seiten  und 30.)",
                "brauchen.(Die Anschriften finden Sie auf Seite 30.)",
            ),
        ],
    )
    def test_missing_left_collapses_to_singular(self, text: str, expected: str):
        result = _clean(text)
        assert result == expected
        assert PARTIAL_PAGE_REF_RE.search(result) is None and EMPTY_PAGE_REF_RE.search(result) is None

    @pytest.mark.parametrize(
        "text, expected",
        [
            # no-number range/multiple lead-in fronting a V2-inverted clause: drop
            # the lead-in and restore <subject> <verb> so it is not verb-first.
            (
                "erhältlich. Auf den Seiten\u00a0 bis  haben wir alle Anschriften.",
                "erhältlich. Wir haben alle Anschriften.",
            ),
            ("Auf den Seiten bis haben wir alles zusammengestellt.", "Wir haben alles zusammengestellt."),
            ("Fertig. Auf den Seiten und geben wir Hinweise.", "Fertig. Wir geben Hinweise."),
            # a different inverted subject pronoun ("… finden Sie …" → "Sie finden …")
            ("Text. Auf den Seiten bis finden Sie Adressen.", "Text. Sie finden Adressen."),
        ],
    )
    def test_sentence_initial_leadin_repaired(self, text: str, expected: str):
        result = _clean(text)
        assert result == expected
        assert PARTIAL_PAGE_REF_RE.search(result) is None and EMPTY_PAGE_REF_RE.search(result) is None

    def test_unrepairable_sentence_initial_leadin_kept_not_mangled(self):
        # Fallback: a sentence-initial lead-in with no recognised inverted subject
        # cannot be grammatically reordered, so it is kept verbatim rather than
        # mangled into a verb-first fragment. (Such a shape does not occur in the
        # corpus; the broad invariant would surface it if one ever appeared.)
        text = "Auf den Seiten bis dahin standen die Daten."
        assert _clean(text) == text


class TestLiteralPlaceholderSiblingTarget:

    def test_kept_when_followed_by_sibling(self):
        # "… auf der Seite " with a URL xref sibling: the trailing locution has a
        # target and must not be stripped.
        assert _clean("das Kundenportal auf der Seite ", followed_by_sibling=True) == "das Kundenportal auf der Seite "

    def test_removed_when_no_sibling(self):
        # Identical text with no following node is an empty placeholder and is
        # excised (a bare trailing space is harmless and dropped by TEXT2MD).
        result = _clean("das Kundenportal auf der Seite ", followed_by_sibling=False)
        assert "auf der Seite" not in result
        assert result.strip() == "das Kundenportal"

    def test_external_url_reference_survives_end_to_end(self):
        # Full XML → HTML: "auf der Seite <a href=URL>" is a valid reference; the
        # rewriter must not delete "auf der Seite" ahead of the external xref.
        html = _to_html(
            '<p>Das Portal auf der Seite <xref scope="external" href="https://drv.example">DRV</xref>, mehr dazu.</p>'
        )
        text = _paragraph_text(html, "Das Portal")
        assert "Das Portal auf der Seite" in text
        assert "<a href='https://drv.example'>DRV</a>" in html


class TestLiteralPlaceholderEndToEnd:

    def _to_md(self, body: str) -> str:
        xml = f'<?xml version="1.0" encoding="UTF-8"?><topic id="T"><title>Doc</title><body>{body}</body></topic>'
        item = PipelineItem(
            name="doc",
            data_object=DataObject(name="doc", data=xml, data_type=DataType.XML, metadata={"name": "doc"}),
        )
        html_item = dita_to_html().apply(item)[0]
        return str(text_to_md().apply(html_item)[0].data_object.data)

    def test_leaf_paragraph_singular_removed(self):
        md = self._to_md("<p>Die Kontaktdaten finden Sie ab Seite .</p>")
        assert "Die Kontaktdaten finden Sie." in md
        assert EMPTY_PAGE_REF_RE.search(md) is None

    def test_phrase_in_footnote_double_prep_removed(self):
        # #204: the placeholder lives inside <fn><ph>…</ph></fn> (a nested leaf).
        md = self._to_md("<p>Text.(Die Anschrift finden Sie <fn><ph>auf ab Seite .</ph></fn>)</p>")
        assert EMPTY_PAGE_REF_RE.search(md) is None
        assert "auf ab Seite" not in md

    def test_sentence_initial_fronted_ref_repaired(self):
        # #305: no-number range lead-in fronting a V2-inverted clause — the
        # lead-in is dropped and "haben wir" restored to "Wir haben" so the
        # resulting German is grammatical (no verb-first fragment, no placeholder).
        md = self._to_md("<p>erhältlich. Auf den Seiten\u00a0 bis  haben wir alle Anschriften.</p>")
        assert "Auf den Seiten" not in md
        assert "erhältlich. Wir haben alle Anschriften." in md
        assert EMPTY_PAGE_REF_RE.search(md) is None and PARTIAL_PAGE_REF_RE.search(md) is None

    def test_missing_left_partial_collapsed_to_singular(self):
        # #407: plural "Seiten" whose first page was dropped, leaving a lone
        # right number — collapsed to the grammatical singular "auf Seite 30".
        md = self._to_md("<p>Die Anschriften finden Sie auf den Seiten\u00a0 und 30.</p>")
        assert "auf den Seiten" not in md
        assert "Die Anschriften finden Sie auf Seite 30." in md
        assert PARTIAL_PAGE_REF_RE.search(md) is None


def _corpus_files() -> list[Path]:
    source_dir = Path(__file__).resolve().parents[5] / "cdk" / "seed-data" / "source"
    return sorted(source_dir.glob("*.xml"))


def _node_text(node: DitaNode) -> str:
    return node.text if node.text else "".join(_node_text(c) for c in node.children)


def _surviving_empty_page_xrefs(node: DitaNode) -> int:
    count = 0
    kids = node.children
    for i, child in enumerate(kids):
        if (
            child.node_type == DitaNodeType.XREF
            and child.attributes.get("scope", "local") != "external"
            and local_element_id(child.attributes.get("href", "")) is not None
            and not _node_text(child)
        ):
            prev = kids[i - 1].text if i > 0 and kids[i - 1].node_type == DitaNodeType.TEXT else ""
            if PAGE_CUE_RE.search(prev) or child.attributes.get("otherprops") == "seitenzahl":
                count += 1
        count += _surviving_empty_page_xrefs(child)
    return count


class TestCorpusScan:

    def test_no_empty_page_xref_survives_rewrite(self):
        """#693 guarantee: every empty printed-page xref is resolved or removed.

        Structural check on the transformed tree — after PageReferenceRewriter no
        empty local xref that is page-cued (or tagged otherprops="seitenzahl")
        remains anywhere, in the primary doc or any nested block context.
        """
        files = _corpus_files()
        assert files, "no seed-data source XML found for corpus scan"

        parser = DitaParser()
        offenders: list[str] = []
        for path in files:
            document = parser.parse_to_model(path.read_text(encoding="utf-8"))
            if document.content is None:
                continue
            PageReferenceRewriter(document.node_dict).rewrite(document.content)
            surviving = _surviving_empty_page_xrefs(document.content)
            if surviving:
                offenders.append(f"{path.name}: {surviving} surviving empty page xref(s)")

        assert not offenders, "empty page cross-references survived the rewrite:\n" + "\n".join(offenders)

    def test_generated_markdown_has_zero_empty_or_partial_page_refs(self):
        """Assert the generated Markdown corpus has zero empty OR partial page refs (#693).

        The broad invariant combines two detectors:

        * :data:`EMPTY_PAGE_REF_RE` — the precise detector for cue-prefixed empty
          slots ending in punctuation (``ab Seite .``, ``auf den Seiten und .``,
          ``siehe Seite bis )``);
        * :data:`PARTIAL_PAGE_REF_RE` — the broad detector for a und/bis/,
          connector sitting directly against ``Seite(n)``, which is the empty-slot
          signal even when a surviving token hides it: a lone right page number
          (``auf den Seiten und 30``) or a fronted clause
          (``Auf den Seiten bis haben wir …``).

        Both must be zero in the generated Markdown, whether the defect came from
        an empty ``<xref/>`` (Component B) or a pure xref-less literal
        (:meth:`PageReferenceRewriter._clean_literal_text`, including its
        missing-left and sentence-initial repairs). Valid references never match
        either detector — a page number binds directly, and a title/URL follows
        without a connector (see :class:`TestEmptyPageRefDetector` /
        :class:`TestPartialPageRefDetector`).

        Both detectors still match the xref-less literals in the *raw* source (the
        print pipeline never emitted the page number), so ``source_hits`` is
        non-zero and proves the corpus really exercises the defect. Word-integrity
        is guarded separately (:class:`TestPageCueWordIntegrity`).
        """
        files = _corpus_files()
        assert files, "no seed-data source XML found for corpus scan"

        detectors = ((EMPTY_PAGE_REF_RE, "empty"), (PARTIAL_PAGE_REF_RE, "partial"))
        source_hits = 0
        offenders: list[str] = []
        for path in files:
            raw = path.read_text(encoding="utf-8")
            # In raw XML a working reference is "Seite <xref .../>." — the '<'
            # breaks both detectors, so on the source they count only the
            # xref-less (literal) defects the transform must now repair.
            source_hits += sum(len(detector.findall(raw)) for detector, _ in detectors)
            item = PipelineItem(
                name=path.name,
                data_object=DataObject(name=path.name, data=raw, data_type=DataType.XML, metadata={"name": path.name}),
            )
            html_item = dita_to_html().apply(item)[0]
            markdown = str(text_to_md().apply(html_item)[0].data_object.data)
            for detector, label in detectors:
                for match in detector.finditer(markdown):
                    context = markdown[max(0, match.start() - 40) : match.end() + 8].replace("\n", " ")
                    offenders.append(f"{path.name} [{label}]: …{context}…")

        assert source_hits > 0, "corpus no longer exercises the empty/partial page-ref defect; the scan is vacuous"
        assert not offenders, "empty or partial printed-page references remain in generated Markdown:\n" + "\n".join(
            offenders
        )
