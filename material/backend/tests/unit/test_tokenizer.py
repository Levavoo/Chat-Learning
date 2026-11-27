"""Tests for BM25 tokenizer: lowercasing, stopword removal, decompounding, Cistem stemming."""

import unittest

from bm25_shared.cistem import Cistem
from bm25_shared.decompound import decompound
from bm25_shared.tokenizer import tokenize


class TestTokenize(unittest.TestCase):
    def test_lowercases_and_splits(self):
        tokens = tokenize("Rente Berechnung")
        self.assertEqual(len(tokens), 2)
        self.assertTrue(all(t == t.lower() for t in tokens))

    def test_removes_stopwords(self):
        self.assertEqual(tokenize("der die das und"), [])

    def test_drops_single_char_tokens(self):
        self.assertEqual(tokenize("a b c x"), [])

    def test_handles_umlauts(self):
        tokens = tokenize("Häuser")
        self.assertEqual(len(tokens), 1)
        self.assertNotIn("ü", tokens[0])
        self.assertNotIn("ä", tokens[0])

    def test_handles_empty_input(self):
        self.assertEqual(tokenize(""), [])

    def test_singular_and_plural_collapse(self):
        self.assertEqual(tokenize("Rente"), tokenize("Renten"))

    def test_adjective_inflections_collapse(self):
        forms = ["medizinisch", "medizinische", "medizinischen", "medizinisches"]
        stems = {tokenize(f)[0] for f in forms}
        self.assertEqual(len(stems), 1, f"expected one stem, got {stems}")

    def test_query_and_document_match_after_stemming(self):
        doc_tokens = tokenize("Die Renten der Versicherten")
        query_tokens = tokenize("Rente Versicherter")
        self.assertTrue(set(query_tokens).issubset(set(doc_tokens)))

    def test_compound_query_matches_simple_doc(self):
        doc_tokens = tokenize("Die Altersrenten und Witwenrenten werden berechnet")
        query_tokens = tokenize("Rente")
        self.assertTrue(set(query_tokens).issubset(set(doc_tokens)))

    def test_simple_query_matches_compound_doc(self):
        doc_tokens = tokenize("Beiträge zur Rentenversicherung")
        self.assertTrue(set(tokenize("Rente")).issubset(set(doc_tokens)))
        self.assertTrue(set(tokenize("Versicherung")).issubset(set(doc_tokens)))


class TestDecompound(unittest.TestCase):
    def test_short_words_not_split(self):
        for w in ["haus", "rente", "reha", "alter"]:
            self.assertEqual(decompound(w), [w])

    def test_non_compounds_preserved(self):
        """Splitting "Versicherung" as Ver|Sicherung would corrupt every Rentenversicherung document."""
        self.assertEqual(decompound("versicherung"), ["versicherung"])
        self.assertEqual(decompound("berechnung"), ["berechnung"])

    def test_pension_domain_compounds_split(self):
        self.assertEqual(decompound("altersrente"), ["alters", "rente"])
        self.assertEqual(decompound("witwenrente"), ["witwen", "rente"])
        self.assertEqual(decompound("rentenversicherung"), ["renten", "versicherung"])

    def test_benefit_geld_compounds_split(self):
        self.assertEqual(decompound("krankengeld"), ["kranken", "geld"])
        self.assertEqual(decompound("wohngeld"), ["wohn", "geld"])
        self.assertEqual(decompound("arbeitslosengeld"), ["arbeitslosen", "geld"])

    def test_pension_modifier_prefix_split(self):
        self.assertEqual(decompound("rentenbescheid"), ["renten", "bescheid"])
        self.assertEqual(decompound("rentenantrag"), ["renten", "antrag"])
        self.assertEqual(decompound("versicherungsverlauf"), ["versicherungs", "verlauf"])
        self.assertEqual(decompound("altersvorsorge"), ["alters", "vorsorge"])
        self.assertEqual(decompound("entgeltpunkte"), ["entgelt", "punkte"])
        self.assertEqual(decompound("beitragsbemessungsgrenze"), ["beitrags", "bemessungsgrenze"])

    def test_generic_word_starts_not_split(self):
        """Generic prefixes must NOT split, or a token like "grund" would scatter across unrelated documents."""
        self.assertEqual(decompound("grundlage"), ["grundlage"])
        self.assertEqual(decompound("grundstück"), ["grundstück"])

    def test_triple_compound_via_recursion(self):
        parts = decompound("krankenversicherungsbeitrag")
        self.assertEqual(len(parts), 3)
        self.assertIn("kranken", parts)
        self.assertIn("beitrag", parts)

    def test_suffix_recursion_for_erwerbsminderungsrente(self):
        parts = decompound("erwerbsminderungsrente")
        self.assertEqual(parts, ["erwerbs", "minderungs", "rente"])

    def test_suffix_plural_form(self):
        parts = decompound("erwerbsminderungsrenten")
        self.assertIn("renten", parts)
        self.assertIn("erwerbs", parts)

    def test_does_not_split_domain_head_alone(self):
        """Guarded by _MIN_REMAINDER_LEN: a head noun on its own must not split into (∅, head)."""
        self.assertEqual(decompound("versicherung"), ["versicherung"])
        self.assertEqual(decompound("leistung"), ["leistung"])

    def test_query_matches_erwerbsminderungsrente_document(self):
        doc_tokens = tokenize("Anspruch auf Erwerbsminderungsrenten besteht")
        self.assertTrue(set(tokenize("Rente")).issubset(set(doc_tokens)))
        self.assertTrue(set(tokenize("Erwerbsminderung")).issubset(set(doc_tokens)))

    def test_empty_string(self):
        self.assertEqual(decompound(""), [""])


class TestCistem(unittest.TestCase):
    def setUp(self):
        self.stemmer = Cistem(case_insensitive=True)

    def test_empty_string(self):
        self.assertEqual(self.stemmer.stem(""), "")

    def test_idempotent(self):
        for word in ["rente", "haus", "berechnen"]:
            stemmed = self.stemmer.stem(word)
            self.assertEqual(self.stemmer.stem(stemmed), stemmed)

    def test_case_sensitive_preserves_noun_t(self):
        """case_insensitive=False: capitalized words keep trailing 't' (noun heuristic)."""
        cs = Cistem(case_insensitive=False)
        self.assertNotEqual(cs.stem("Brot"), cs.stem("brot"))


if __name__ == "__main__":
    unittest.main()
