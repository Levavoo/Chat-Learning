"""Offline unit tests for the #501 Merkblatt Markdown renderer.

No Textract, no boto3, no AWS — only the pure ``render_sections_to_markdown`` /
``_neutralise_headings`` helpers operating on in-memory ``process_blocks``-shaped
dicts. These lock the KB-shipping contract: one flat ``## `` per un-split
section, an empty-title intro promoted to a synthetic heading, never an ``###``,
and stray heading markers in content neutralised so KB routing stays flat.
"""

import re

from etl.util.merkblatt_markdown import (
    SYNTHETIC_INTRO_HEADING,
    _neutralise_headings,
    render_sections_to_markdown,
)

# The exact detectors the KB chunker uses (chunk_markdown / flat_section_strategy):
# H2 sections via a line-anchored "## ", hierarchical routing via "\n### ".
_H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def _count_h2(md: str) -> int:
    return len(_H2_RE.findall(md))


def _count_h3(md: str) -> int:
    return md.count("\n### ")


class TestRenderSectionsToMarkdown:

    def test_each_section_becomes_one_h2(self):
        doc = {
            "doc_id": "G0103",
            "title": "Merkblatt G0103",
            "sections": [
                {"title": "Frage eins?", "content": "Antwort eins."},
                {"title": "Frage zwei?", "content": "Antwort zwei."},
                {"title": "Frage drei?", "content": "Antwort drei."},
            ],
        }
        md = render_sections_to_markdown(doc)

        assert _count_h2(md) == 3
        assert _count_h3(md) == 0
        assert "## Frage eins?" in md
        assert "Antwort eins." in md
        # Each heading is separated from its body by a blank line.
        assert "## Frage eins?\n\nAntwort eins." in md

    def test_empty_title_intro_uses_doc_title(self):
        doc = {
            "doc_id": "V0090",
            "title": "Hinweis zur Aufrechterhaltung des Versicherungsschutzes",
            "sections": [
                {"title": "", "content": "V0090\nDieses Hinweisblatt informiert Sie ..."},
                {"title": "Ist mein Versicherungsschutz gefährdet?", "content": "Der Anspruch ..."},
            ],
        }
        md = render_sections_to_markdown(doc)

        assert md.startswith("## Hinweis zur Aufrechterhaltung des Versicherungsschutzes\n\n")
        # Intro content is preserved (not dropped as preamble).
        assert "Dieses Hinweisblatt informiert Sie" in md
        assert _count_h2(md) == 2

    def test_empty_title_intro_falls_back_to_ueberblick(self):
        doc = {
            "doc_id": "X0001",
            "title": "",
            "sections": [{"title": "", "content": "Nur Fließtext ohne Überschrift."}],
        }
        md = render_sections_to_markdown(doc)

        assert md.startswith(f"## {SYNTHETIC_INTRO_HEADING}\n\n")
        assert _count_h2(md) == 1

    def test_never_emits_h3(self):
        doc = {
            "doc_id": "R0101",
            "title": "Merkblatt R0101",
            "sections": [{"title": f"Abschnitt {i}", "content": f"Inhalt {i}"} for i in range(5)],
        }
        md = render_sections_to_markdown(doc)

        assert _count_h3(md) == 0
        assert "### " not in md

    def test_does_not_pre_split_large_sections(self):
        big = "Ein Satz über die Rente. " * 400  # ~10k chars, well over MAX_SECTION_CHARS
        doc = {
            "doc_id": "G0103",
            "title": "Merkblatt G0103",
            "sections": [{"title": "Große Sektion", "content": big}],
        }
        md = render_sections_to_markdown(doc)

        assert _count_h2(md) == 1
        assert "(Teil 1)" not in md and "(Teil 2)" not in md
        assert big.strip() in md

    def test_stray_heading_markers_in_content_are_neutralised(self):
        content = (
            "Normaler Absatz.\n"
            "### Versteckte Überschrift\n"
            "## Auch eine Überschrift\n"
            "#KeinHeading ohne Leerzeichen\n"
            "Text mit # mitten im Satz."
        )
        doc = {
            "doc_id": "V0090",
            "title": "Merkblatt V0090",
            "sections": [{"title": "Echte Sektion", "content": content}],
        }
        md = render_sections_to_markdown(doc)

        # Exactly the one real section heading; the stray "## "/"### " lines are inert.
        assert _count_h2(md) == 1
        assert _count_h3(md) == 0
        # Visible text is preserved (escaped, not removed).
        assert "Versteckte Überschrift" in md
        assert "Auch eine Überschrift" in md
        assert "#KeinHeading ohne Leerzeichen" in md
        assert "Text mit # mitten im Satz." in md

    def test_handles_missing_sections_key(self):
        assert render_sections_to_markdown({"doc_id": "V0001", "title": "T", "sections": []}) == ""

    def test_strips_trailing_line_whitespace_and_uses_one_final_newline(self):
        doc = {
            "doc_id": "R0501",
            "title": "Merkblatt",
            "sections": [{"title": "Tabelle", "content": "Wert | \nNoch ein Wert |  "}],
        }

        md = render_sections_to_markdown(doc)

        assert md == "## Tabelle\n\nWert |\nNoch ein Wert |\n"

    def test_empty_section_has_only_one_blank_line_before_next_heading(self):
        doc = {
            "doc_id": "R0101",
            "title": "Merkblatt",
            "sections": [
                {"title": "Anlagen", "content": ""},
                {"title": "Unterlagen", "content": "Inhalt"},
            ],
        }

        assert render_sections_to_markdown(doc) == "## Anlagen\n\n## Unterlagen\n\nInhalt\n"


class TestNeutraliseHeadings:

    def test_escapes_leading_h2_and_h3(self):
        assert _neutralise_headings("### Titel") == r"\### Titel"
        assert _neutralise_headings("## Titel") == r"\## Titel"
        assert _neutralise_headings("# Titel") == r"\# Titel"

    def test_leaves_hash_without_space_untouched(self):
        # Not a valid ATX heading (needs whitespace after the run), so left as-is.
        assert _neutralise_headings("#hashtag") == "#hashtag"

    def test_leaves_mid_line_hash_untouched(self):
        assert _neutralise_headings("Kosten # 5 beachten") == "Kosten # 5 beachten"

    def test_escapes_only_first_run_per_line_multiline(self):
        text = "Zeile eins\n## Zwei\nZeile drei\n### Vier"
        out = _neutralise_headings(text)
        assert out == "Zeile eins\n\\## Zwei\nZeile drei\n\\### Vier"

    def test_no_h3_substring_after_neutralisation(self):
        # The KB hierarchical-routing detector counts "\n### "; escaping removes it.
        text = "Absatz\n### Eins\n### Zwei\n### Drei"
        out = _neutralise_headings(text)
        assert out.count("\n### ") == 0
