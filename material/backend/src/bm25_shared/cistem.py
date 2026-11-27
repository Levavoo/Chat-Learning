"""CISTEM — a character-based stemmer for German.

Vendored reference implementation. Original by Leonie Weissweiler & Alexander
Fraser, MIT-licensed (https://github.com/LeonieWeissweiler/CISTEM).

Reference:
  Weissweiler, L. & Fraser, A. (2017). "Developing a Stemmer for German Based
  on a Comparative Analysis of Publicly Available Stemmers." In Proceedings of
  the German Society for Computational Linguistics (GSCL).

Vendored (not pip-installed) because no standalone PyPI package exists — the
algorithm is small, stable, and pulling NLTK just for this would bloat the
Lambda image.
"""

import re

_STRIP_GE = re.compile(r"^ge(.{4,})")
_REPL_XX = re.compile(r"(.)\1")
_REPL_XX_BACK = re.compile(r"(.)\*")


class Cistem:
    """German stemmer using the CISTEM algorithm.

    Args:
        case_insensitive: When True, the algorithm does not rely on the input's
            original capitalization. Set True if the caller already lowercased
            the text — otherwise the noun-detection heuristic (which uses
            capitalization to decide whether to strip a trailing "t") is broken.

    """

    def __init__(self, case_insensitive: bool = False) -> None:
        self._case_insensitive = case_insensitive

    def stem(self, word: str) -> str:
        if not word:
            return word

        upper = word[0].isupper()
        word = word.lower()

        word = word.replace("ü", "u").replace("ö", "o").replace("ä", "a").replace("ß", "ss")
        word = _STRIP_GE.sub(r"\1", word)
        word = self._collapse(word)

        while len(word) > 3:
            if len(word) > 5 and word.endswith(("em", "er", "nd")):
                word = word[:-2]
                continue
            # Only strip a trailing "t" for non-noun-looking words (lowercase
            # original) — German nouns are capitalized and shouldn't lose "t".
            if (not upper or self._case_insensitive) and word.endswith("t"):
                word = word[:-1]
                continue
            if word.endswith(("e", "s", "n")):
                word = word[:-1]
                continue
            break

        return self._expand(word)

    @staticmethod
    def _collapse(word: str) -> str:
        word = word.replace("sch", "$").replace("ei", "%").replace("ie", "&")
        return _REPL_XX.sub(r"\1*", word)

    @staticmethod
    def _expand(word: str) -> str:
        word = _REPL_XX_BACK.sub(r"\1\1", word)
        return word.replace("$", "sch").replace("%", "ei").replace("&", "ie")
