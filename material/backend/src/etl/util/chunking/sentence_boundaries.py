"""German-aware sentence boundary detection for chunk splitting.

Deliberately conservative: a missed boundary only costs a slightly less elegant
cut, while a false boundary cuts a chunk mid-sentence — the defect this module
exists to prevent (#503). Every rule therefore errs towards "not a boundary".
"""

import re

# Tokens that end with a period without ending a sentence. Stored without the
# period and lower-cased. Single letters cover spaced forms such as "z. B.",
# "u. a.", "d. h." and "i. d. R.", where each element is its own token.
_ABBREVIATIONS = frozenset({
    "nr",
    "abs",
    "art",
    "buchst",
    "bzw",
    "ca",
    "evtl",
    "ggf",
    "inkl",
    "exkl",
    "vgl",
    "usw",
    "etc",
    "bspw",
    "insb",
    "sog",
    "mind",
    "max",
    "kap",
    "pkt",
    "ebd",
    "ff",
    "f",
    "s",
    "abb",
    "tab",
    "str",
    "aufl",
    "dr",
    "prof",
    "dipl",
    "med",
    "jur",
    "phil",
    "mio",
    "mrd",
    "tsd",
    "a",
    "b",
    "d",
    "e",
    "h",
    "i",
    "o",
    "r",
    "u",
    "v",
    "z",
    "jan",
    "feb",
    "mrz",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "okt",
    "nov",
    "dez",
})

# Sentence-final punctuation followed by whitespace. NBSP counts as whitespace
# because the DITA corpus uses it inside figures and dates.
_CANDIDATE_RE = re.compile(r"[.!?…](?=[\s\u00a0])")
_WORD_BEFORE_RE = re.compile(r"([A-Za-zÄÖÜäöüß]+)\Z")
_INLINE_SPACE = " \t\u00a0"
# Characters that can legitimately open the next sentence besides a capital.
_SENTENCE_OPENERS = "\u201e\u201c\"'\u00bb\u00ab(-\u2013\u2014*#>[0123456789"


def is_sentence_end(text: str, index: int) -> bool:
    """Return whether the punctuation at ``index`` ends a sentence."""
    if index < 0 or index >= len(text):
        return False

    char = text[index]
    if char == ".":
        previous = text[index - 1] if index else ""
        # Ordinals, decimals and enumerations: "1. Januar", "Nr. 5", "3.5".
        if previous.isdigit():
            return False
        word = _WORD_BEFORE_RE.search(text, 0, index)
        if word and word.group(1).lower() in _ABBREVIATIONS:
            return False

    position = index + 1
    while position < len(text) and text[position] in _INLINE_SPACE:
        position += 1
    if position >= len(text):
        return True

    following = text[position]
    if following == "\n":
        return True
    return following.isupper() or following in _SENTENCE_OPENERS


def last_sentence_end(text: str, start: int, end: int) -> int | None:
    """Return the index just past the last sentence end within ``[start, end)``."""
    best: int | None = None
    for match in _CANDIDATE_RE.finditer(text, max(start, 0), end):
        if is_sentence_end(text, match.start()):
            best = match.start() + 1
    return best


def split_sentences(text: str) -> list[str]:
    """Split ``text`` into sentence spans without losing characters."""
    spans: list[str] = []
    previous = 0
    for match in _CANDIDATE_RE.finditer(text):
        if is_sentence_end(text, match.start()):
            spans.append(text[previous : match.start() + 1])
            previous = match.start() + 1
    if previous < len(text):
        spans.append(text[previous:])
    return spans


def pack_by_sentences(text: str, target: int) -> list[str] | None:
    """Greedily pack whole sentences into pieces of at most ``target`` chars.

    Returns None when ``text`` holds fewer than two sentences. A single sentence
    longer than ``target`` is emitted oversized; the caller splits it further.
    """
    sentences = split_sentences(text)
    if len(sentences) < 2:
        return None

    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = current + sentence
        if current and len(candidate) > target:
            pieces.append(current.strip())
            current = sentence.lstrip()
        else:
            current = candidate
    if current.strip():
        pieces.append(current.strip())
    return pieces
