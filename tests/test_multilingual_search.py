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

    def _search(
        self,
        query: str,
        *,
        match: str = "whole_word",
        words: str = "all",
        diacritics: str = "sensitive",
        exclude: tuple[str, ...] = (),
    ) -> dict:
        return self.bible.search(
            query,
            "multi",
            SearchBible(
                match=match,
                words=words,
                diacritics=diacritics,
                exclude=exclude,
            ),
        )

    @staticmethod
    def _verse_numbers(response: dict) -> list[int]:
        return [int(match["verse"]) for match in response["matches"]]

    def test_simplified_chinese_short_substrings_match_inside_unsegmented_text(
        self,
    ) -> None:
        one_character = self._search("神", match="substring")
        two_characters = self._search("神爱", match="substring")

        self.assertEqual(self._verse_numbers(one_character), [1, 2, 3, 4, 19])
        self.assertEqual(self._verse_numbers(two_characters), [1, 2])
        self.assertEqual(two_characters["query"]["total"], 2)
        self.assertEqual(two_characters["query"]["engine_version"], 2)

    def test_repeated_han_substrings_report_every_occurrence_in_one_token(
        self,
    ) -> None:
        response = self._search("神", match="substring")
        repeated = next(
            match for match in response["matches"] if int(match["verse"]) == 19
        )

        self.assertEqual(repeated["occurrences"], 3)

    def test_traditional_chinese_is_searched_without_conflating_script_variants(
        self,
    ) -> None:
        traditional = self._search("神愛", match="substring")
        simplified = self._search("神爱", match="substring")

        self.assertEqual(self._verse_numbers(traditional), [3])
        self.assertEqual(self._verse_numbers(simplified), [1, 2])

    def test_chinese_punctuation_creates_a_whole_word_boundary(self) -> None:
        response = self._search("起初")

        self.assertEqual(self._verse_numbers(response), [1, 3])
        self.assertEqual(response["query"]["total"], 2)

    def test_whole_word_does_not_claim_an_internal_chinese_match(self) -> None:
        response = self._search("神")

        self.assertEqual(response["query"]["total"], 0)
        self.assertEqual(response["matches"], [])

    def test_japanese_short_substring_matches_inside_an_unsegmented_token(
        self,
    ) -> None:
        substring = self._search("めに", match="substring")
        whole_word = self._search("めに")

        self.assertEqual(self._verse_numbers(substring), [4])
        self.assertEqual(whole_word["query"]["total"], 0)

    def test_japanese_short_substring_accepts_prolonged_sound_mark(self) -> None:
        substring = self._search("アー", match="substring")
        whole_word = self._search("アー")

        self.assertEqual(self._verse_numbers(substring), [20])
        self.assertEqual(whole_word["query"]["total"], 0)

    def test_korean_short_substring_matches_an_inflected_word(self) -> None:
        substring = self._search("천지", match="substring")
        whole_word = self._search("천지")

        self.assertEqual(self._verse_numbers(substring), [5])
        self.assertEqual(whole_word["query"]["total"], 0)

    def test_thai_short_substring_matches_text_without_spaces(self) -> None:
        substring = self._search("ใน", match="substring")
        whole_word = self._search("ใน")

        self.assertEqual(self._verse_numbers(substring), [13])
        self.assertEqual(whole_word["query"]["total"], 0)

    def test_lao_short_substring_matches_text_without_word_boundaries(self) -> None:
        substring = self._search("ໃນ", match="substring")
        whole_word = self._search("ໃນ")

        self.assertEqual(self._verse_numbers(substring), [16])
        self.assertEqual(whole_word["query"]["total"], 0)

    def test_khmer_short_substring_matches_text_without_word_boundaries(self) -> None:
        substring = self._search("កា", match="substring")
        whole_word = self._search("កា")

        self.assertEqual(self._verse_numbers(substring), [17])
        self.assertEqual(whole_word["query"]["total"], 0)

    def test_myanmar_short_substring_matches_text_without_word_boundaries(self) -> None:
        substring = self._search("အစ", match="substring")
        whole_word = self._search("အစ")

        self.assertEqual(self._verse_numbers(substring), [18])
        self.assertEqual(whole_word["query"]["total"], 0)

    def test_mixed_scripts_remain_searchable_across_unicode_punctuation(self) -> None:
        response = self._search(
            "Jesus 耶稣",
            match="substring",
            words="all",
        )

        self.assertEqual(self._verse_numbers(response), [15])
        self.assertEqual(response["matches"][0]["terms"], ["jesus", "耶稣"])

    def test_short_unsegmented_exclusion_uses_the_same_validation_policy(
        self,
    ) -> None:
        response = self._search(
            "起初",
            match="substring",
            exclude=("爱",),
        )

        self.assertEqual(self._verse_numbers(response), [3])
        self.assertEqual(response["query"]["total"], 1)

    def test_arabic_whole_words_and_arabic_comma_are_tokenized_correctly(
        self,
    ) -> None:
        response = self._search("الكلمة")

        self.assertEqual(self._verse_numbers(response), [7])
        self.assertEqual(response["matches"][0]["occurrences"], 2)

    def test_arabic_diacritic_insensitive_search_matches_pointed_text(self) -> None:
        sensitive = self._search("في")
        insensitive = self._search("في", diacritics="insensitive")

        self.assertEqual(self._verse_numbers(sensitive), [7])
        self.assertEqual(self._verse_numbers(insensitive), [6, 7])

    def test_arabic_canonical_equivalence_is_normalized_to_nfc(self) -> None:
        response = self._search("ا\u0655له")

        self.assertEqual(self._verse_numbers(response), [8])
        self.assertEqual(response["matches"][0]["terms"], ["إله"])

    def test_hebrew_diacritic_insensitive_search_matches_pointed_text(self) -> None:
        sensitive = self._search("בראשית")
        insensitive = self._search("בראשית", diacritics="insensitive")

        self.assertEqual(self._verse_numbers(sensitive), [10])
        self.assertEqual(self._verse_numbers(insensitive), [9, 10])

    def test_short_hebrew_whole_word_is_not_blocked_by_substring_limits(
        self,
    ) -> None:
        response = self._search("את", diacritics="insensitive")

        self.assertEqual(self._verse_numbers(response), [9, 10])
        self.assertEqual(response["matches"][0]["occurrences"], 1)
        self.assertEqual(response["matches"][1]["occurrences"], 1)

    def test_devanagari_whole_words_respect_spaces_and_danda_punctuation(
        self,
    ) -> None:
        response = self._search("की")

        self.assertEqual(self._verse_numbers(response), [11])
        self.assertEqual(response["matches"][0]["occurrences"], 2)

    def test_devanagari_canonical_equivalence_normalizes_nukta_forms(self) -> None:
        response = self._search("क़ानून")

        self.assertEqual(self._verse_numbers(response), [12])
        self.assertEqual(response["matches"][0]["terms"], ["क़ानून"])

    def test_join_controls_remain_inside_arabic_and_devanagari_tokens(self) -> None:
        persian = self._search("می‌رود")
        devanagari = self._search("क्‍ष")

        self.assertEqual(self._verse_numbers(persian), [21])
        self.assertEqual(self._verse_numbers(devanagari), [22])

    def test_short_substring_floor_remains_for_segmented_scripts(self) -> None:
        for query in ("go", "في", "את", "की"):
            with self.subTest(query=query), self.assertRaises(SearchValidationError):
                self._search(query, match="substring")

    def test_mixed_latin_and_han_short_token_cannot_bypass_substring_floor(
        self,
    ) -> None:
        with self.assertRaises(SearchValidationError):
            self._search("a神", match="substring")


if __name__ == "__main__":
    unittest.main()
