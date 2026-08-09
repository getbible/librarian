"""Script-aware analysis and positional indexing.

Expectations are asserted against the repository's own multilingual fixture so
every case is real text in the API's JSON contract rather than a construction
made to fit the implementation.
"""

import json
import unittest
from pathlib import Path

from getbible.search.analysis import (
    Analyzer,
    ScriptFamily,
    classify_text,
    fold_marks,
    normalize_book_name,
)
from getbible.search.index import build_index, chain_matches, merge_verses

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "multilingual_repository"
    / "v2"
    / "multi.json"
)


def _fixture_verses() -> dict[int, str]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {
        int(verse["verse"]): verse["text"]
        for book in data["books"]
        for chapter in book["chapters"]
        for verse in chapter["verses"]
    }


VERSES = _fixture_verses()


class TestScriptClassification(unittest.TestCase):
    def test_each_fixture_verse_lands_in_its_writing_system(self) -> None:
        expected = {
            1: ScriptFamily.CONTINUOUS,   # Simplified Chinese
            3: ScriptFamily.CONTINUOUS,   # Traditional Chinese
            4: ScriptFamily.CONTINUOUS,   # Japanese
            5: ScriptFamily.CONTINUOUS,   # Korean
            6: ScriptFamily.ABJAD,        # Arabic with harakat
            9: ScriptFamily.ABJAD,        # Hebrew with niqqud
            11: ScriptFamily.BRAHMIC,     # Devanagari
            13: ScriptFamily.CONTINUOUS,  # Thai
            16: ScriptFamily.CONTINUOUS,  # Lao
            17: ScriptFamily.CONTINUOUS,  # Khmer
            18: ScriptFamily.CONTINUOUS,  # Myanmar
        }
        for verse, family in expected.items():
            with self.subTest(verse=verse):
                self.assertIs(classify_text(VERSES[verse]), family)

    def test_latin_text_is_alphabetic(self) -> None:
        self.assertIs(classify_text("In the beginning God"), ScriptFamily.ALPHABETIC)


class TestAnalyzer(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = Analyzer()

    def _terms(self, text: str) -> list[str]:
        return [token.term for token in self.analyzer.tokens(text)]

    def test_continuous_runs_produce_unigrams_and_bigrams(self) -> None:
        terms = self._terms("神爱世人")

        self.assertEqual(
            terms,
            ["神", "神爱", "爱", "爱世", "世", "世人", "人"],
        )

    def test_pointed_and_unpointed_hebrew_analyse_identically(self) -> None:
        pointed = set(self._terms(VERSES[9]))
        plain = set(self._terms(VERSES[10]))

        self.assertEqual(pointed, plain)
        self.assertIn("בראשית", pointed)

    def test_arabic_article_yields_a_stem_beside_the_written_word(self) -> None:
        terms = self._terms(VERSES[6])

        self.assertIn("البدء", terms)
        self.assertIn("بدء", terms)

    def test_triliteral_words_are_not_falsely_stemmed(self) -> None:
        # Stripping a particle letter off a three-letter root would invent a
        # stem that is not a word: Hebrew "ברא" and Arabic "الله".
        self.assertNotIn("רא", self._terms("ברא"))
        self.assertNotIn("له", self._terms("الله"))

    def test_brahmic_combining_marks_are_preserved(self) -> None:
        terms = self._terms(VERSES[11])

        self.assertIn("पृथ्वी", terms)
        self.assertNotIn("पथवी", terms)

    def test_script_punctuation_bounds_a_run(self) -> None:
        # The Hebrew sof pasuq must not become part of the preceding word.
        self.assertIn("הארץ", self._terms("הָאָרֶץ׃"))

    def test_mixed_script_verse_analyses_each_run_by_its_own_rules(self) -> None:
        terms = self._terms(VERSES[15])

        self.assertIn("jesus", terms)      # Latin stays a whole word
        self.assertIn("耶稣", terms)        # Han becomes n-grams
        self.assertIn("예수", terms)        # Hangul becomes n-grams
        self.assertNotIn("jesus耶稣", terms)

    def test_accents_fold_so_unaccented_queries_reach_accented_text(self) -> None:
        self.assertEqual(self._terms("λόγος"), self._terms("λογος"))
        self.assertEqual(self._terms("Ðức Chúa Trời"), self._terms("Duc Chua Troi"))

    def test_case_sensitive_analyzer_keeps_case(self) -> None:
        sensitive = Analyzer(case_sensitive=True)

        self.assertEqual(
            [token.term for token in sensitive.tokens("God")], ["God"]
        )

    def test_diacritic_sensitive_analyzer_keeps_marks(self) -> None:
        exact = Analyzer(fold_diacritics=False)

        self.assertEqual([token.term for token in exact.tokens("ἀγάπη")], ["ἀγάπη"])
        self.assertEqual([token.term for token in self.analyzer.tokens("ἀγάπη")], ["αγαπη"])

    def test_case_folding_expands_greek_letters_that_unicode_decomposes(self) -> None:
        # Full case folding turns the iota subscript into a written iota. Both
        # sides of a search pass through the same rule, so the forms still meet.
        self.assertEqual(
            [token.term for token in self.analyzer.tokens("ἀγάπῃ")],
            [token.term for token in self.analyzer.tokens("αγαπηι")],
        )

    def test_greek_final_sigma_folds_to_medial_sigma(self) -> None:
        # Unicode case folding unifies ς and σ, so a reader reaches the verse
        # whichever form they type. This holds even when marks are preserved.
        for analyzer in (Analyzer(), Analyzer(fold_diacritics=False)):
            with self.subTest(fold=analyzer.fold_diacritics):
                self.assertEqual(
                    [token.term for token in analyzer.tokens("λόγος")],
                    [token.term for token in analyzer.tokens("λόγοσ")],
                )

    def test_fold_marks_reaches_precomposed_letters(self) -> None:
        self.assertEqual(fold_marks("Đường ø ł"), "Duong o l")

    def test_book_names_fold_for_lookup(self) -> None:
        self.assertEqual(normalize_book_name("1 Cor."), "1cor")


class TestPositionalIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.texts = [VERSES[number] for number in sorted(VERSES)]
        self.index = build_index(self.texts, Analyzer())

    def _ordinal(self, verse: int) -> int:
        return sorted(VERSES).index(verse)

    def test_postings_record_every_occurrence_with_its_position(self) -> None:
        # Verse 19 is "神神创造神。" — three occurrences of 神 in one verse.
        postings = self.index.get("神")
        ordinal = self._ordinal(19)

        self.assertEqual(len(postings.positions_in(ordinal)), 3)

    def test_document_frequency_counts_verses_not_occurrences(self) -> None:
        self.assertEqual(
            self.index.frequency("神"),
            sum(1 for text in self.texts if "神" in text),
        )

    def test_chain_matches_finds_multi_character_runs_exactly(self) -> None:
        analyzer = Analyzer()
        matched = chain_matches(self.index, analyzer.tokens("神爱世人"))
        found = {self.texts[ordinal] for ordinal in matched}

        self.assertEqual(found, {VERSES[1], VERSES[2]})

    def test_chain_matches_rejects_characters_that_are_merely_co_present(self) -> None:
        # Verse 19 contains 神 and 造 but never the sequence 神造.
        matched = chain_matches(self.index, Analyzer().tokens("神造"))

        self.assertNotIn(self._ordinal(19), matched)

    def test_chain_matches_agrees_with_a_plain_substring_scan(self) -> None:
        analyzer = Analyzer()
        for query in ("神爱世人", "起初", "神創造", "世人", "예수", "イエス"):
            with self.subTest(query=query):
                matched = set(chain_matches(self.index, analyzer.tokens(query)))
                expected = {
                    ordinal
                    for ordinal, text in enumerate(self.index.texts)
                    if query.casefold() in text
                }
                self.assertEqual(matched, expected)

    def test_traditional_and_simplified_stay_distinct(self) -> None:
        analyzer = Analyzer()
        traditional = set(chain_matches(self.index, analyzer.tokens("神愛")))
        simplified = set(chain_matches(self.index, analyzer.tokens("神爱")))

        self.assertEqual({self.texts[o] for o in traditional}, {VERSES[3]})
        self.assertEqual(
            {self.texts[o] for o in simplified}, {VERSES[1], VERSES[2]}
        )

    def test_trigram_candidates_match_a_brute_force_scan(self) -> None:
        for fragment in ("ראש", "بدء", "eru", "पृथ"):
            with self.subTest(fragment=fragment):
                self.assertEqual(
                    set(self.index.terms_containing(fragment)),
                    {term for term in self.index.postings if fragment in term},
                )

    def test_analysis_report_describes_the_translation(self) -> None:
        report = self.index.analysis_report()

        self.assertEqual(report["dominant_script"], ScriptFamily.CONTINUOUS.value)
        self.assertFalse(report["case_sensitive"])
        self.assertTrue(report["fold_diacritics"])

    def test_merge_verses_is_empty_when_any_group_is_empty(self) -> None:
        self.assertEqual(merge_verses([{1, 2}, set()]), set())
        self.assertEqual(merge_verses([{1, 2, 3}, {2, 3, 4}]), {2, 3})


if __name__ == "__main__":
    unittest.main()


class TestProximityWindows(unittest.TestCase):
    """Proximity must find a qualifying window whenever one exists."""

    def setUp(self) -> None:
        from getbible.search.analysis import ScriptFamily as SF
        from getbible.search.engine import QueryUnit, _within_proximity

        self.check = _within_proximity
        self.unit = lambda offset: QueryUnit("x", (), SF.ALPHABETIC, offset, 1)

    def _units(self, count: int) -> list:
        return [self.unit(index) for index in range(count)]

    def test_a_distant_first_occurrence_does_not_hide_a_close_pair(self) -> None:
        # Anchoring on the first occurrence of the first unit and taking each
        # other unit's nearest position misses the window at 40/41.
        resolved = [{0: [0, 40]}, {0: [41]}]

        self.assertTrue(self.check(resolved, self._units(2), 0, 0))

    def test_three_units_find_their_tightest_window(self) -> None:
        resolved = [{0: [1, 30]}, {0: [15, 31]}, {0: [16, 32]}]

        self.assertTrue(self.check(resolved, self._units(3), 0, 0))
        self.assertFalse(self.check(resolved, self._units(3), 0, -1))

    def test_a_unit_absent_from_the_verse_fails(self) -> None:
        resolved = [{0: [1]}, {}]

        self.assertFalse(self.check(resolved, self._units(2), 0, 100))

    def test_intervening_units_are_counted(self) -> None:
        resolved = [{0: [0]}, {0: [3]}]

        self.assertFalse(self.check(resolved, self._units(2), 0, 1))
        self.assertTrue(self.check(resolved, self._units(2), 0, 2))

    def test_a_repeated_unit_asks_for_two_occurrences(self) -> None:
        # "faith faith" under proximity means two occurrences close together,
        # so the duplicate must survive into matching.
        from getbible.search import SearchBible
        from getbible.search.engine import validate_search_request
        from getbible.search.limits import SearchLimits

        _, units, _ = validate_search_request(
            "faith faith", SearchBible(proximity=3), SearchLimits()
        )
        _, collapsed, _ = validate_search_request(
            "faith faith", SearchBible(), SearchLimits()
        )

        self.assertEqual(len(units), 2)
        self.assertEqual(len(collapsed), 1)
