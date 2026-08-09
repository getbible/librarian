"""Multilingual search under the 2.0 contract.

The governing expectation of this file is that a caller supplies a query string
and nothing else. Every writing system in the fixture is reached by the default
criteria, so none of these tests select a match mode to make a script work.
"""

import tempfile
import unittest
from pathlib import Path

from getbible import GetBible, SearchBible, SearchValidationError

FIXTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "multilingual_repository"


class TestMultilingualSearch(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.bible = GetBible(
            repo_path=FIXTURE_REPOSITORY,
            cache_dir=self.temporary.name,
        )

    def tearDown(self) -> None:
        self.bible.close()
        self.temporary.cleanup()

    def _search(self, query: str, **criteria: object) -> dict:
        """Search with the library's defaults unless a test overrides them."""
        return self.bible.search(query, "multi", SearchBible(**criteria))

    @staticmethod
    def _verse_numbers(response: dict) -> list[int]:
        return [int(match["verse"]) for match in response["matches"]]


class TestContinuousScripts(TestMultilingualSearch):
    """Scripts that do not delimit words with spaces."""

    def test_chinese_is_found_without_choosing_a_match_mode(self) -> None:
        one_character = self._search("神")
        two_characters = self._search("神爱")

        self.assertEqual(self._verse_numbers(one_character), [1, 2, 3, 4, 19])
        self.assertEqual(self._verse_numbers(two_characters), [1, 2])
        self.assertEqual(two_characters["query"]["total"], 2)

    def test_whole_word_and_substring_agree_in_continuous_scripts(self) -> None:
        # Nothing delimits a word, so there is no boundary for the two modes to
        # disagree about. A caller cannot get this wrong by choosing either.
        for query in ("神", "神爱", "起初"):
            with self.subTest(query=query):
                self.assertEqual(
                    self._verse_numbers(self._search(query)),
                    self._verse_numbers(self._search(query, match="substring")),
                )

    def test_every_continuous_script_is_reached_by_default(self) -> None:
        expected = {
            "めに": [4],     # Japanese kana
            "アー": [20],    # Katakana with a prolonged sound mark
            "천지": [5],     # Korean, inside an inflected word
            "ใน": [13],     # Thai
            "ໃນ": [16],     # Lao
            "កា": [17],     # Khmer
            "အစ": [18],     # Myanmar
        }
        for query, verses in expected.items():
            with self.subTest(query=query):
                self.assertEqual(self._verse_numbers(self._search(query)), verses)

    def test_traditional_and_simplified_are_not_conflated(self) -> None:
        self.assertEqual(self._verse_numbers(self._search("神愛")), [3])
        self.assertEqual(self._verse_numbers(self._search("神爱")), [1, 2])

    def test_a_run_must_occur_in_order_not_merely_be_present(self) -> None:
        # Verse 19 is "神神创造神。" — it holds 神 and 创造, never 神创造神爱.
        self.assertEqual(self._search("创造神爱")["query"]["total"], 0)

    def test_repeated_characters_report_every_occurrence(self) -> None:
        response = self._search("神")
        repeated = next(
            match for match in response["matches"] if int(match["verse"]) == 19
        )

        self.assertEqual(repeated["occurrences"], 3)

    def test_chinese_punctuation_bounds_a_run(self) -> None:
        self.assertEqual(self._verse_numbers(self._search("起初")), [1, 3])

    def test_exclusions_use_the_same_analysis_as_the_query(self) -> None:
        response = self._search("起初", exclude=("爱",))

        self.assertEqual(self._verse_numbers(response), [3])
        self.assertEqual(response["query"]["total"], 1)


class TestAbjadScripts(TestMultilingualSearch):
    """Hebrew and Arabic: optional vowel pointing and attached particles."""

    def test_unpointed_hebrew_reaches_pointed_text_by_default(self) -> None:
        self.assertEqual(self._verse_numbers(self._search("בראשית")), [9, 10])

    def test_exact_diacritics_still_distinguishes_pointing(self) -> None:
        self.assertEqual(
            self._verse_numbers(self._search("בראשית", diacritics="exact")), [10]
        )

    def test_unvowelled_arabic_reaches_text_with_harakat(self) -> None:
        self.assertEqual(self._verse_numbers(self._search("في")), [6, 7])
        self.assertEqual(
            self._verse_numbers(self._search("في", diacritics="exact")), [7]
        )

    def test_an_attached_particle_does_not_hide_the_word(self) -> None:
        # "بدء" is written as "الْبَدْءِ" and "بِالْبَدْءِ" in the fixture. A reader
        # types the stem; the engine indexes it beside the written form.
        self.assertEqual(self._verse_numbers(self._search("بدء")), [6, 7, 8])

    def test_the_written_form_is_still_matched_exactly(self) -> None:
        self.assertEqual(self._verse_numbers(self._search("بِالْبَدْءِ")), [8])

    def test_arabic_whole_words_and_arabic_comma_are_bounded(self) -> None:
        response = self._search("الكلمة")

        self.assertEqual(self._verse_numbers(response), [7])
        self.assertEqual(response["matches"][0]["occurrences"], 2)

    def test_short_hebrew_words_are_not_blocked(self) -> None:
        response = self._search("את")

        self.assertEqual(self._verse_numbers(response), [9, 10])
        self.assertEqual(response["matches"][0]["occurrences"], 1)

    def test_canonical_equivalence_is_normalized(self) -> None:
        self.assertEqual(self._verse_numbers(self._search("إله")), [8])


class TestBrahmicScripts(TestMultilingualSearch):
    """Devanagari: combining marks carry vowels and are never folded away."""

    def test_whole_words_respect_spaces_and_danda(self) -> None:
        response = self._search("की")

        self.assertEqual(self._verse_numbers(response), [11])
        self.assertEqual(response["matches"][0]["occurrences"], 2)

    def test_nukta_forms_normalize_without_losing_the_mark(self) -> None:
        response = self._search("क़ानून")

        self.assertEqual(self._verse_numbers(response), [12])
        self.assertEqual(response["matches"][0]["terms"], ["क़ानून"])

    def test_join_controls_stay_inside_their_word(self) -> None:
        self.assertEqual(self._verse_numbers(self._search("می‌رود")), [21])
        self.assertEqual(self._verse_numbers(self._search("क्‍ष")), [22])

        # The controls join each written word. Its fragments must not become
        # independent whole-word postings merely because both sides analyse
        # text using the same rules.
        self.assertNotIn(21, self._verse_numbers(self._search("می")))
        self.assertNotIn(22, self._verse_numbers(self._search("क्")))


class TestMixedScripts(TestMultilingualSearch):
    def test_each_part_of_a_mixed_query_keeps_its_own_rules(self) -> None:
        response = self._search("Jesus 耶稣")

        self.assertEqual(self._verse_numbers(response), [15])
        self.assertEqual(response["matches"][0]["terms"], ["jesus", "耶稣"])

    def test_a_han_character_does_not_loosen_the_latin_part(self) -> None:
        # Under 1.x an application flipped the whole query to substring when it
        # saw any Han, so "all" began matching inside "shall". Each run now
        # carries its own rules, so the Latin word stays a whole word.
        self.assertEqual(self._search("Jesu 耶稣")["query"]["total"], 0)


class TestSubstringPolicy(TestMultilingualSearch):
    def test_the_substring_floor_applies_only_to_space_delimited_scripts(self) -> None:
        # A one- or two-letter Latin fragment matches much of a vocabulary. The
        # same length in Hebrew, Arabic or Devanagari is an ordinary word, and
        # the index answers it exactly rather than by scanning.
        with self.assertRaises(SearchValidationError):
            self._search("go", match="substring")
        for query, verses in {"في": [6, 7], "את": [9, 10], "की": [11]}.items():
            with self.subTest(query=query):
                self.assertEqual(
                    self._verse_numbers(self._search(query, match="substring")), verses
                )

    def test_a_short_latin_run_is_still_floored_in_a_mixed_query(self) -> None:
        with self.assertRaises(SearchValidationError):
            self._search("a神", match="substring")


class TestResponseContract(TestMultilingualSearch):
    def test_engine_version_marks_the_matching_change(self) -> None:
        # Downstream result caches key on this, so it must move when matching
        # semantics change without a translation SHA changing.
        self.assertEqual(self._search("神")["query"]["engine_version"], 4)

    def test_the_response_reports_how_the_translation_was_read(self) -> None:
        self.assertEqual(
            self._search("神")["query"]["analysis"], {"script": "continuous"}
        )

    def test_results_keep_the_select_structure(self) -> None:
        response = self._search("神爱")
        chapter = next(iter(response["results"].values()))

        self.assertIn("verses", chapter)
        self.assertIn("ref", chapter)
        self.assertEqual(chapter["abbreviation"], "multi")


if __name__ == "__main__":
    unittest.main()
