"""Resolve and rewrite empty DITA local cross-references (#693).

DRV brochures encode every in-document reference as an *empty, self-closing*
``<xref scope="local" href="#TOPIC/elem"/>`` whose visible value (a printed page
number, or a chapter title) is produced only by the print pipeline. When such a
document is converted for the knowledge base the value is lost, leaving broken
prose such as ``... ab Seite .`` or ``... unser Kapitel „“.``.

This module provides two things used by :mod:`etl.transform.convert_to_html`:

* resolution helpers (:func:`local_element_id`, :func:`resolve_local_target`,
  :func:`heading_title`) that fix the topic-qualified href lookup, and
* :class:`PageReferenceRewriter`, a structural pre-render pass that turns empty
  page locutions into grammatical prose (or a resolved titled reference) and
  restores genuine chapter references.

The pass is pure and deterministic: no network, no LLM, no I/O.
"""

import re

from etl.util.parsing.dita import DitaNode, DitaNodeType

# Whitespace class covering the regular space plus the two zero-width / no-break
# fillers DRV exports sprinkle around references (U+00A0 no-break space,
# U+FEFF zero-width no-break space).
_WS = r"[\s\u00a0\ufeff]"

# German typographic quotes used by the source: „ (U+201E) opening,
# “ (U+201C) / ” (U+201D) closing.
_QUOTE_OPEN = "\u201e\u201c"
_QUOTE_CLOSE = "\u201c\u201d"

# A page cue at the *end* of the text immediately preceding an empty local xref,
# e.g. "auf den Seiten", "ab Seite", "siehe Seite", or a bare "Seite"/"Seiten".
# The optional preposition + article are part of the cue so Tier 2 removal can
# delete the whole span ("auf den Seiten <xref/>" -> "").
#
# Every token is word-bounded (\b): the cue must never match *inside* a word, or
# it would silently truncate real prose — "Internetseite" -> "Internet", "jeder
# Seite" -> "je" (#693 review). The optional prefix/article groups carry their
# own \b, so they skip cleanly (match empty) when the preceding word merely ends
# in "der"/"auf" etc., while still removing a genuine leading "ab"/"auf den".
# \b/\w are Unicode-aware for str patterns, so German umlauts (ä/ö/ü/ß) count as
# word characters and bound compounds correctly.
PAGE_CUE_RE = re.compile(
    rf"(?:\b(?:auf|ab|siehe|vgl\.?))?{_WS}*(?:\b(?:der|den|die|dem)\b)?{_WS}*\bSeiten?\b{_WS}*$",
    re.IGNORECASE,
)

# A bare connector between two xrefs of one locution: "und" (multiple) / "bis"
# (range). Matches the whole text node so ", weitere Infos" does not qualify.
CONNECTOR_RE = re.compile(rf"^{_WS}*(und|bis){_WS}*$", re.IGNORECASE)

# Detector used by the acceptance scan (Component C). Matches a *broken* printed
# page reference: a page cue ("auf"/"ab"/"siehe"/"vgl") optionally followed by an
# article, then "Seite(n)", optional und/bis/, connectors, and terminal
# punctuation with no page number in between — "ab Seite .", "auf den Seiten und
# .", "siehe Seite bis )". Requiring the leading cue keeps legitimate prose out
# ("an Ihrer Seite.", "auf der Startseite.", "32 Seiten)"), and a real "ab Seite
# 12." never matches because the digit breaks the run before the punctuation.
EMPTY_PAGE_REF_RE = re.compile(
    rf"\b(?:auf|ab|siehe|vgl\.?){_WS}+(?:der|den|die|dem)?{_WS}*Seiten?{_WS}*(?:(?:und|bis|,){_WS}*)*[.,;:)]",
    re.IGNORECASE,
)

# A page-number cue preposition that introduces a printed page reference.
# "siehe auch Seite …" is a common variant, so an optional "auch" is allowed
# after the preposition. The leading \b keeps it from matching inside a word.
_PAGE_PREP = rf"\b(?:auf|ab|siehe|vgl\.?)(?:{_WS}+auch\b)?"

# A *literal* (xref-less) empty page-number placeholder in prose — the #693
# residual class. The print pipeline injects the page number right after
# "Seite(n)"; in the KB export that slot is empty, leaving "… ab Seite ." or
# "… auf den Seiten  bis .". This matches the whole reference span (cue →
# Seite(n) → empty und/bis/, connectors → trailing whitespace) so the rewriter
# can excise it and re-normalise the surrounding prose.
#
# Precision guards keep it strictly off valid references and ordinary prose
# (every case verified against the seed-data corpus):
#   * a cue preposition is required, so idioms and counts are safe
#     ("an Ihrer Seite", "zur Seite", "32 Seiten", "die erste Seite");
#   * the article must sit *directly* before "Seite(n)", so a described page is
#     safe ("auf der nächsten Seite", "auf den folgenden Seiten" — the adjective
#     breaks the adjacency);
#   * the two number look-aheads skip real references — an immediate page number
#     ("auf Seite 12") and a connector that reaches a number ("auf den Seiten
#     und 30");
#   * the trailing look-ahead skips a title or URL that follows the cue
#     ("auf den Seiten \"Checkliste …\"", "auf der Seite [www…]").
# Sentence-position (a fronted adverbial whose removal would leave a verb-first
# fragment) is handled by the rewriter, not here.
_LITERAL_PAGE_REF_RE = re.compile(
    rf"(?:{_PAGE_PREP}{_WS}*)+"
    rf"(?:\b(?:der|den|die|dem)\b{_WS}*)?"
    rf"\bSeiten?\b"
    rf"(?!{_WS}*\d)"
    rf"(?!(?:{_WS}*(?:und|bis|,))+{_WS}*\d)"
    rf"(?:{_WS}*(?:und|bis|,)\b)*"
    rf'(?!{_WS}*[\d\[{_QUOTE_OPEN}"])'
    rf"{_WS}*",
    re.IGNORECASE,
)

# --- #693 follow-up: *partial* (not merely empty) printed-page references -----
#
# Two malformed shapes survive the empty-placeholder pass above because a
# surviving token hides the dropped page number, so EMPTY_PAGE_REF_RE and
# _LITERAL_PAGE_REF_RE (both keyed on an *empty* slot ending in punctuation)
# deliberately skip them:
#   * missing-left + real-right — plural "Seiten" whose first number was dropped,
#     leaving a lone right number: "… auf den Seiten  und 30.";
#   * no-number range/multiple lead-in fronting a clause — both numbers dropped
#     at the start of a sentence: "… Auf den Seiten  bis haben wir …".
# Both are objectively ungrammatical partial references, not valid ones.

# Broad detector used by the corpus invariant: a page cue + optional article +
# "Seite(n)" with a und/bis/, connector sitting *directly* against "Seite(n)"
# (only whitespace between) always means the left page number was dropped — the
# reference is empty ("auf den Seiten und ."), missing-left ("auf den Seiten und
# 30"), or a no-number lead-in ("Auf den Seiten bis haben wir …"). A valid
# reference never places a connector against "Seite(n)": a real page number binds
# directly ("auf Seite 12", "auf den Seiten 12 und 13") and a title/URL follows
# with no connector ("auf den Seiten „Checkliste …“", "auf der Seite [www…]").
# The required leading cue keeps bibliographic page counts out ("512 Seiten,
# Schutzgebühr …" has a number before "Seiten" and no cue).
PARTIAL_PAGE_REF_RE = re.compile(
    rf"{_PAGE_PREP}{_WS}*"
    rf"(?:\b(?:der|den|die|dem)\b{_WS}*)?"
    rf"\bSeiten?\b{_WS}*"
    rf"(?:und|bis|,)",
    re.IGNORECASE,
)

# Missing-left partial: "Seite(n)" + empty first slot + connector(s) + a real
# page number. The plural is now ungrammatical (only one page survived), so the
# whole locution collapses to the singular "<cue> Seite <n>" — the article is
# dropped ("auf Seite 30", never "auf den Seite 30"). A complete "Seiten 12 und
# 30" never matches: the "12" between "Seiten" and the connector breaks the
# adjacency the pattern requires.
_PARTIAL_MISSING_LEFT_RE = re.compile(
    rf"\b(?P<cue>auf|ab|siehe|vgl\.?)(?:{_WS}+auch\b)?{_WS}*"
    rf"(?:\b(?:der|den|die|dem)\b{_WS}*)?"
    rf"\bSeiten?\b{_WS}*"
    rf"(?:(?:und|bis|,){_WS}*)+"
    rf"(?P<num>\d+)",
    re.IGNORECASE,
)

# German subject pronouns that can trail a fronted element under verb-second
# inversion — the tail of a fronted-adverbial clause ("… haben wir …").
_INVERSION_SUBJECT = r"(?:wir|ich|du|er|sie|es|ihr|man)"

# No-number range/multiple lead-in fronting a declarative clause. German
# verb-second word order puts <finite-verb> <subject-pronoun> right after a
# fronted adverbial ("Auf den Seiten bis haben wir …"). The print pipeline
# dropped both page numbers, leaving an empty-slot lead-in; deleting it bare
# would leave an ungrammatical verb-first fragment ("… haben wir …"). Capturing
# the inverted verb + subject lets the rewriter drop the lead-in and restore
# <subject> <verb> ("Wir haben …"). The letters-only verb group plus the pronoun
# requirement keep this off real references: "Auf Seite 5 und 6 haben wir …"
# keeps its numbers and never matches — the digit blocks connector-adjacency.
_SENTENCE_INITIAL_LEADIN_RE = re.compile(
    rf"\b(?:auf|ab|siehe|vgl\.?)(?:{_WS}+auch\b)?{_WS}*"
    rf"(?:\b(?:der|den|die|dem)\b{_WS}*)?"
    rf"\bSeiten?\b{_WS}*"
    rf"(?:(?:und|bis|,){_WS}*)+"
    rf"(?P<verb>[^\W\d_]+){_WS}+"
    rf"(?P<subj>{_INVERSION_SUBJECT})\b",
    re.IGNORECASE,
)

_WS_COLLAPSE_RE = re.compile(rf"{_WS}+")
_SPACE_BEFORE_PUNCT_RE = re.compile(rf"{_WS}+([.,;:!?)])")
_EMPTY_PARENS_RE = re.compile(rf"\({_WS}*\)")
_EMPTY_QUOTES_RE = re.compile(rf"[{_QUOTE_OPEN}]{_WS}*[{_QUOTE_CLOSE}]")
_DANGLING_CONNECTOR_RE = re.compile(rf"{_WS}*(?:,|;|\bund\b|\bbis\b){_WS}*([.,;:!?)])", re.IGNORECASE)


def local_element_id(href: str) -> str | None:
    """Return the bare element id of a local href, or ``None`` if not local.

    ``"#B19-20-w298a/drv-ec7792da-…"`` -> ``"drv-ec7792da-…"`` (topic-qualified);
    ``"#test-section"`` -> ``"test-section"`` (single segment);
    ``"other-topic.dita"`` -> ``None``.
    """
    if not href.startswith("#"):
        return None
    return href[1:].split("/")[-1]


def resolve_local_target(href: str, node_dict: dict[str, DitaNode]) -> DitaNode | None:
    element_id = local_element_id(href)
    if element_id is None:
        return None
    return node_dict.get(element_id)


def heading_title(node: DitaNode | None) -> str | None:
    """Return a node's heading title, or ``None`` when it is not a heading.

    Only ``SECTION`` and ``TITLE`` are label-eligible: every other node type
    returns ``None`` so a reference is never masked with inline body text
    (#693 constraint).
    """
    if node is None:
        return None
    if node.node_type == DitaNodeType.TITLE:
        return node.text or None
    if node.node_type == DitaNodeType.SECTION:
        for child in node.children:
            if child.node_type == DitaNodeType.TITLE:
                return child.text or None
    return None


def _node_text(node: DitaNode) -> str:
    """Concatenate all descendant text of a node (for emptiness checks)."""
    if node.text:
        return node.text
    return "".join(_node_text(child) for child in node.children)


def _text_node(text: str) -> DitaNode:
    return DitaNode(node_type=DitaNodeType.TEXT, text=text)


class PageReferenceRewriter:
    """Rewrite empty local page/chapter xrefs on the parsed DITA node tree.

    Runs after parse and before HTML render, in place. Because the renderer
    recurses through every block context (``<p>``, ``<li>``, ``<entry>``,
    ``<ph>``/``<fn>``, ``<note>``, subheading), one recursive pre-pass over the
    document content covers them all — including the ``<topic>`` sub-documents
    that :mod:`etl.transform.extract_dita_notes` / ``extract_dita_tables`` feed
    back through this transform. Only *empty local* xrefs are touched; external
    xrefs and any local xref carrying explicit text are left untouched.
    """

    def __init__(self, node_dict: dict[str, DitaNode]) -> None:
        self._node_dict = node_dict

    def rewrite(self, node: DitaNode) -> None:
        """Rewrite empty page/chapter references on the tree, in place.

        Two complementary passes:

        * :meth:`_rewrite_children` handles empty local *xref* locutions using
          their sibling prose cue (#693 Component B);
        * :meth:`_clean_literal_text` handles *xref-less* literal placeholders
          (``… ab Seite .``, ``… auf den Seiten  bis .``) that carry no xref to
          key off — the #693 residual class — wherever prose text lives: a
          leaf node's ``text`` or a ``TEXT`` child inside a children list.

        A ``CODEBLOCK`` holds preformatted text and is never rewritten.
        """
        if node.children:
            node.children = self._rewrite_children(node.children)
            last = len(node.children) - 1
            for index, child in enumerate(node.children):
                if child.node_type == DitaNodeType.TEXT:
                    child.text = self._clean_literal_text(child.text, followed_by_sibling=index < last)
            node.children = [
                child for child in node.children if child.node_type != DitaNodeType.TEXT or child.text != ""
            ]
            for child in node.children:
                if child.node_type != DitaNodeType.TEXT:
                    self.rewrite(child)
        elif node.text and node.node_type != DitaNodeType.CODEBLOCK:
            node.text = self._clean_literal_text(node.text)

    @classmethod
    def _clean_literal_text(cls, text: str, followed_by_sibling: bool = False) -> str:
        """Repair xref-less literal page-number placeholders in prose text.

        Three passes run in order, then the result is re-normalised. Text that
        carries none of the defects is returned unchanged, so ordinary prose
        (legitimate ``Seite`` mentions, page counts, intentional spacing) and
        valid references (a real page number, a titled/URL reference) are never
        touched.

        1. **Missing-left partial → grammatical singular**
           (:meth:`_collapse_to_singular_page`) — "… auf den Seiten  und 30." →
           "… auf Seite 30.". The plural whose first page was dropped is wrong;
           the lone surviving number becomes a singular reference.
        2. **No-number lead-in fronting a clause → restored word order**
           (:meth:`_repair_sentence_initial_leadin`) — "… Auf den Seiten  bis
           haben wir …" → "… Wir haben …". A sentence-initial adverbial whose
           page numbers were dropped is removed and the verb-second inversion it
           fronted is swapped back to a grammatical declarative order.
        3. **Empty placeholder → removed**
           (:meth:`_excise_empty_literal_placeholders`) — the residual
           ``_LITERAL_PAGE_REF_RE`` spans (cue → ``Seite(n)`` → empty
           connectors → punctuation).

        Passes 1 and 2 must run *before* pass 3's ``_LITERAL_PAGE_REF_RE`` search:
        both target shapes that regex deliberately skips (a surviving page
        number, or a fronted clause), so they cannot sit behind its early exit.
        """
        repaired = _PARTIAL_MISSING_LEFT_RE.sub(cls._collapse_to_singular_page, text)
        repaired = cls._repair_sentence_initial_leadin(repaired)

        if _LITERAL_PAGE_REF_RE.search(repaired):
            repaired = cls._excise_empty_literal_placeholders(repaired, followed_by_sibling)

        if repaired == text:
            return text
        return cls._normalise(repaired)

    @staticmethod
    def _collapse_to_singular_page(match: re.Match[str]) -> str:
        """Collapse a missing-left partial to the singular ``<cue> Seite <n>`` (#693).

        The lone surviving page number becomes the reference and the now-wrong
        plural article is dropped ("auf den Seiten  und 30" -> "auf Seite 30").
        """
        return f"{match.group('cue')} Seite {match.group('num')}"

    @classmethod
    def _repair_sentence_initial_leadin(cls, text: str) -> str:
        """Drop a sentence-initial no-number page-ref lead-in, restoring word order (#693).

        "… erhältlich. Auf den Seiten  bis haben wir alle Anschriften." →
        "… erhältlich. Wir haben alle Anschriften."

        Only fires when the lead-in is genuinely sentence-initial (start of text
        or right after ``.!?:``); a mid-sentence match is returned verbatim (the
        existing empty-placeholder pass handles a mid-sentence lead-in by plain
        removal, which is already grammatical there).
        """

        def _repair(match: re.Match[str]) -> str:
            preceding = text[: match.start()].rstrip()
            if preceding and preceding[-1] not in ".!?:":
                return match.group(0)
            subj = match.group("subj")
            return f"{subj[:1].upper()}{subj[1:]} {match.group('verb')}"

        return _SENTENCE_INITIAL_LEADIN_RE.sub(_repair, text)

    @staticmethod
    def _excise_empty_literal_placeholders(text: str, followed_by_sibling: bool) -> str:
        """Remove xref-less empty page-number placeholders (``_LITERAL_PAGE_REF_RE``).

        A locution is left in place in two cases:

        * **sentence-initial and resuming with a word** — a residual fronted
          adverbial (``"Auf den Seiten  bis haben wir …"``) that
          :meth:`_repair_sentence_initial_leadin` could not rewrite (no
          recognised inverted subject). Removing it bare would leave an
          ungrammatical verb-first fragment, so it is kept rather than mangled.
        * **at the end of the text with a following sibling** — the reference
          target lives in the next node, e.g. ``"… auf der Seite "`` immediately
          followed by an external ``<xref>`` URL, or ``"… auf den Seiten "``
          followed by a titled reference. Empty local-xref locutions are already
          resolved by :meth:`_rewrite_children`, so a surviving end-of-text
          locution before a sibling is a genuine reference, not an empty slot.
        """

        def _replace(match: re.Match[str]) -> str:
            if followed_by_sibling and match.end() == len(text):
                return match.group(0)
            preceding = text[: match.start()].rstrip()
            following = text[match.end() : match.end() + 1]
            sentence_initial = not preceding or preceding[-1] in ".!?"
            resumes_with_word = following.isalpha()
            if sentence_initial and resumes_with_word:
                return match.group(0)
            return ""

        return _LITERAL_PAGE_REF_RE.sub(_replace, text)

    def _is_empty_local_xref(self, node: DitaNode) -> bool:
        if node.node_type != DitaNodeType.XREF:
            return False
        if node.attributes.get("scope", "local") == "external":
            return False
        if local_element_id(node.attributes.get("href", "")) is None:
            return False
        return not _node_text(node)

    def _is_page_ref(self, node: DitaNode, preceding_text: str) -> bool:
        if node.attributes.get("otherprops") == "seitenzahl":
            return True
        return bool(PAGE_CUE_RE.search(preceding_text))

    def _rewrite_children(self, children: list[DitaNode]) -> list[DitaNode]:
        result: list[DitaNode] = []
        index = 0
        total = len(children)
        changed = False

        while index < total:
            node = children[index]
            if not self._is_empty_local_xref(node):
                result.append(node)
                index += 1
                continue

            changed = True
            prev = result[-1] if result and result[-1].node_type == DitaNodeType.TEXT else None
            prev_text = prev.text if prev is not None else ""

            if self._is_page_ref(node, prev_text):
                index = self._rewrite_page_locution(children, index, result, prev)
            else:
                self._rewrite_chapter_ref(node, result)
                index += 1

        if changed:
            result = self._merge_and_normalise(result)
        return result

    def _rewrite_page_locution(
        self,
        children: list[DitaNode],
        start: int,
        result: list[DitaNode],
        prev: DitaNode | None,
    ) -> int:
        """Consume a whole page locution and rewrite it (Tier 1 / Tier 2).

        Returns the index of the first child *after* the locution.
        """
        xrefs = [children[start]]
        connectors: list[str] = []
        cursor = start + 1
        total = len(children)
        while (
            cursor + 1 < total
            and children[cursor].node_type == DitaNodeType.TEXT
            and CONNECTOR_RE.match(children[cursor].text)
            and self._is_empty_local_xref(children[cursor + 1])
        ):
            connectors.append(children[cursor].text)
            xrefs.append(children[cursor + 1])
            cursor += 2

        titles = [heading_title(resolve_local_target(x.attributes.get("href", ""), self._node_dict)) for x in xrefs]

        if prev is not None:
            prev.text = PAGE_CUE_RE.sub("", prev.text)

        if prev is not None and all(title is not None for title in titles):
            # Tier 1 — every target is a heading: emit a titled reference.
            result.append(_text_node(self._build_titled_reference(titles, connectors)))
        # Tier 2 — otherwise the locution (already trimmed off ``prev``) and its
        # xrefs/connectors are simply dropped; normalisation cleans the rest.
        return cursor

    def _rewrite_chapter_ref(self, node: DitaNode, result: list[DitaNode]) -> None:
        """Restore a chapter/title reference, or drop it when unresolved."""
        title = heading_title(resolve_local_target(node.attributes.get("href", ""), self._node_dict))
        if title is not None:
            result.append(_text_node(title))
        # Unresolved (paragraph / sub-doc target): drop the empty xref; any
        # surrounding „ “ pair is removed during normalisation.

    @staticmethod
    def _build_titled_reference(titles: list[str | None], connectors: list[str]) -> str:
        """Build the Tier 1 replacement (leading space; collapsed later).

        Each gap uses its own source connector word ("und"/"bis") so a mixed
        locution ("Seiten X und Y bis Z") keeps its grammar
        ("… „X“ und „Y“ bis „Z“") instead of collapsing every gap to "bis"
        (#693 review). ``connectors`` always has exactly ``len(titles) - 1``
        entries (one per additional xref).
        """
        quoted = [f"\u201e{title}\u201c" for title in titles]
        if len(quoted) == 1:
            return f" im Abschnitt {quoted[0]}"
        parts = [quoted[0]]
        for connector, title in zip(connectors, quoted[1:], strict=True):
            word = "bis" if connector.strip().lower() == "bis" else "und"
            parts.append(f" {word} {title}")
        return f" in den Abschnitten {''.join(parts)}"

    def _merge_and_normalise(self, nodes: list[DitaNode]) -> list[DitaNode]:
        merged: list[DitaNode] = []
        for node in nodes:
            if node.node_type == DitaNodeType.TEXT and merged and merged[-1].node_type == DitaNodeType.TEXT:
                merged[-1].text += node.text
            else:
                merged.append(node)
        for node in merged:
            if node.node_type == DitaNodeType.TEXT:
                node.text = self._normalise(node.text)
        return [node for node in merged if node.node_type != DitaNodeType.TEXT or node.text != ""]

    @staticmethod
    def _normalise(text: str) -> str:
        text = _WS_COLLAPSE_RE.sub(" ", text)
        text = _EMPTY_PARENS_RE.sub("", text)
        text = _EMPTY_QUOTES_RE.sub("", text)
        text = _DANGLING_CONNECTOR_RE.sub(r"\1", text)
        text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
        return text
