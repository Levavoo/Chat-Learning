from bm25_shared.frontmatter import strip_frontmatter


def test_strips_leading_frontmatter_block():
    text = "---\nname: Beitragszahlung\nkeywords: Beitrag, Handwerker\n---\n\n# Titel\n\nText."
    assert strip_frontmatter(text) == "# Titel\n\nText."


def test_no_op_when_absent():
    text = "# Titel\n\nText ohne Frontmatter."
    assert strip_frontmatter(text) == text


def test_idempotent():
    text = "---\ntitle: X\n---\nBody"
    once = strip_frontmatter(text)
    assert strip_frontmatter(once) == once


def test_only_leading_block_removed():
    """A `---` inside the body (a thematic break) is not treated as frontmatter."""
    text = "# Titel\n\nAbschnitt A\n\n---\n\nAbschnitt B"
    assert strip_frontmatter(text) == text


def test_empty_string():
    assert strip_frontmatter("") == ""
