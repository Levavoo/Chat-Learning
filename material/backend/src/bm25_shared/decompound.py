"""German compound splitter for BM25 tokenization.

Splits German compounds into their constituent nouns before stemming, so a
query for "Rente" matches documents about "Altersrenten" or "Rentenbescheide".
Cistem alone is a *suffix* stripper and never splits compounds, so without this
a "Rente" query scores zero against an "Altersrenten" document.

This is a rule-based splitter keyed on the head/modifier nouns of the German
pension domain, in two directions:

  * **Suffix rules** — split a word that *ends* in a known head noun
    (``Altersrente`` → ``alters`` | ``rente``, ``Krankengeld`` →
    ``kranken`` | ``geld``).
  * **Prefix rules** — split a word that *starts* with a known pension
    modifier whose head is an ordinary noun (``Rentenbescheid`` →
    ``renten`` | ``bescheid``, ``Versicherungsverlauf`` →
    ``versicherungs`` | ``verlauf``). Without this, a bare "Rente" /
    "Versicherung" query can't reach those documents through decompounding.

These boundaries are extremely reliable in German — essentially no common word
ends in ``-rente`` or starts with ``renten-`` without being a pension compound —
so the rules are precise *and* free of the heavyweight statistical models
(CharSplit and its ~13 MB / >3 GB-to-compile n-gram tables) that general-purpose
splitters need. The trade-off is that compounds whose only boundary is a *generic*
word (e.g. ``Zugangsfaktor``, ``Wartezeit``) are left whole — domain affixes are
added deliberately, one at a time (as was done for ``entgelt-``/``beitrags-``),
because generic affixes like ``-zeit`` or ``-faktor`` would scatter high-frequency
tokens across unrelated documents.
"""

# Don't try to split words shorter than this — short German words are almost
# never compounds, and short splits are usually nonsense ("Berechnung" → "Ber|Echnung").
_MIN_SPLIT_LEN = 8

# How many times to recursively re-split a part. 2 handles the common triple
# compounds we see in the pension domain (e.g. Krankenversicherungsbeitrag →
# Kranken|Versicherungs|Beitrag) without runaway over-splitting.
_MAX_DEPTH = 2

# Don't split if the part left over after removing a head/modifier would be tiny —
# guards against splitting words like "Rente" itself or producing 2-char fragments.
_MIN_REMAINDER_LEN = 4

# Pension-domain head nouns: we force-split a long word that *ends* in one of
# these. They are extremely reliable as suffix boundaries — there are essentially
# no common non-pension words ending in -rente or -versicherung. This list is the
# main precision↔recall lever for compounds the rules should cover.
_BASE_HEADS = (
    "versicherung",
    "minderung",
    "versorgung",
    "leistung",
    "zahlung",
    "beitrag",
    "schutz",
    "rente",
    "geld",  # benefit terms: Krankengeld, Wohngeld, Arbeitslosengeld, Kindergeld, …
)
# Accept Fugen-s and Fugen-n variants (Versicherungs-, Renten-). Cistem
# normalises the trailing letter away later, so the matched token ends up
# identical regardless of which variant we stripped.
# Longest first so endswith picks the most specific match. `key=lambda s: -len(s)`
# (not `key=len, reverse=True`) because `len` accepts any `Sized`, which widens
# the item type back through `sorted` and makes the static checker reject `.endswith()`.
_DOMAIN_HEAD_SUFFIXES: tuple[str, ...] = tuple(
    sorted(
        {h + linker for h in _BASE_HEADS for linker in ("", "s", "n")},
        key=lambda s: -len(s),
    )
)

# Pension-domain *modifiers* that lead compounds whose head is an ordinary noun
# (Rentenbescheid, Versicherungsverlauf, Altersvorsorge, Krankenkasse,
# Entgeltpunkte, Beitragsbemessungsgrenze). The linking letter is already baked
# into each entry. Longest first so the most specific modifier wins (e.g.
# "versicherungs" before any shorter overlap).
#
# These are all *domain-specific* word-starts: a word beginning with "entgelt-"
# or "beitrags-" is reliably a pension compound, so splitting off the modifier
# only creates useful matches. We deliberately do NOT add generic starts like
# "grund-" or "zeit-": those lead countless unrelated words (Grundlage,
# Grundstück, Zeitpunkt), so splitting them would scatter a high-frequency
# token across unrelated documents and inject false-positive matches.
_DOMAIN_PREFIX_MODIFIERS: tuple[str, ...] = tuple(
    sorted(
        ("renten", "versicherungs", "alters", "kranken", "entgelt", "beitrags"),
        key=lambda s: -len(s),
    )
)


def _try_suffix_split(word: str) -> tuple[str, str] | None:
    """Return (prefix, head) if `word` ends in a known domain head, else None."""
    for suffix in _DOMAIN_HEAD_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_REMAINDER_LEN:
            return word[: -len(suffix)], suffix
    return None


def _try_prefix_split(word: str) -> tuple[str, str] | None:
    """Return (modifier, head) if `word` starts with a known modifier, else None."""
    for modifier in _DOMAIN_PREFIX_MODIFIERS:
        if word.startswith(modifier) and len(word) - len(modifier) >= _MIN_REMAINDER_LEN:
            return modifier, word[len(modifier) :]
    return None


def decompound(word: str, _depth: int = 0) -> list[str]:
    """Split a German compound into constituent parts; return [word] otherwise.

    The returned pieces are lowercased, ready to feed to the stemmer.
    """
    if len(word) < _MIN_SPLIT_LEN or _depth >= _MAX_DEPTH:
        return [word]

    # Head-noun suffix split first — recurse the modifier so multi-modifier
    # prefixes like "erwerbsminderungs" still split into ("erwerbs", "minderungs").
    suffix_split = _try_suffix_split(word)
    if suffix_split:
        modifier, head = suffix_split
        return [*decompound(modifier, _depth + 1), head]

    # Modifier prefix split — recurse the head so "rentenversicherungs…" chains
    # keep peeling. Catches Rentenbescheid / Versicherungsverlauf / Altersvorsorge,
    # where the head is an ordinary noun the suffix rules don't know.
    prefix_split = _try_prefix_split(word)
    if prefix_split:
        modifier, head = prefix_split
        return [modifier, *decompound(head, _depth + 1)]

    return [word]
