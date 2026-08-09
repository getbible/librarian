import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from getbible import (
    SEARCH_ENGINE_VERSION,
    GetBible,
    SearchBible,
    SearchLimitError,
    SearchLimits,
    SearchValidationError,
    requires_substring_matching,
)

FIXTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "multilingual_repository"


class TestMultilingualSearchLimits(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _bible(self, limits: SearchLimits | None = None) -> GetBible:
        bible = GetBible(
            repo_path=FIXTURE_REPOSITORY,
            cache_dir=self.temporary.name,
            search_limits=limits,
        )
        self.addCleanup(bible.close)
        return bible

    def test_filter_size_limits_reject_before_repository_access(self) -> None:
        bible = self._bible()
        oversized_filters = {
            "book item": SearchBible(books=("b" * 257,)),
            "book aggregate": SearchBible(books=("b" * 256,) * 17),
            "exclusion item": SearchBible(exclude=("x" * 501,)),
            "exclusion aggregate": SearchBible(exclude=("x" * 500,) * 9),
        }

        with (
            patch.object(bible, "valid_translation") as valid_translation,
            patch.object(bible._translation_cache, "load") as load_translation,
        ):
            for name, criteria in oversized_filters.items():
                with self.subTest(name=name), self.assertRaises(SearchLimitError):
                    bible.search("faith", "multi", criteria)

        valid_translation.assert_not_called()
        load_translation.assert_not_called()

    def test_punctuation_cannot_pad_a_short_segmented_phrase(self) -> None:
        bible = self._bible()

        with (
            patch.object(bible, "valid_translation") as valid_translation,
            patch.object(bible._translation_cache, "load") as load_translation,
            self.assertRaises(SearchValidationError),
        ):
            bible.search(
                "a!!",
                "multi",
                SearchBible(words="phrase", match="substring"),
            )

        valid_translation.assert_not_called()
        load_translation.assert_not_called()

    def test_abjad_substrings_are_not_subject_to_the_latin_floor(self) -> None:
        # A two-letter Arabic or Hebrew fragment is an ordinary word, and the
        # index answers it exactly instead of scanning, so the floor that keeps
        # open-ended Latin scans in check does not apply.
        bible = self._bible()

        response = bible.search("فِي", "multi", SearchBible(match="substring"))

        self.assertEqual(response["query"]["total"], 2)

    def test_standalone_combining_marks_are_not_search_terms(self) -> None:
        bible = self._bible()

        with (
            patch.object(bible, "valid_translation") as valid_translation,
            patch.object(bible._translation_cache, "load") as load_translation,
            self.assertRaises(SearchValidationError),
        ):
            bible.search("\u0301\u0650", "multi")

        valid_translation.assert_not_called()
        load_translation.assert_not_called()

    def test_the_deprecated_match_mode_helper_no_longer_asks_for_anything(
        self,
    ) -> None:
        # 1.x asked applications to detect continuous scripts and switch to
        # substring. The engine derives that itself now, so the helper reports
        # that no caller-side change is required, for every script.
        self.assertEqual(SEARCH_ENGINE_VERSION, 3)

        for script, query in {
            "Han": "神",
            "Hiragana": "め",
            "Thai": "ใน",
            "Hangul": "한글",
            "Arabic": "العربية",
            "Hebrew": "עברית",
            "Latin": "faith",
        }.items():
            with self.subTest(script=script):
                self.assertFalse(requires_substring_matching(query))

        with self.assertRaises(TypeError):
            requires_substring_matching(None)  # type: ignore[arg-type]

    def test_short_unsegmented_terms_fit_a_tight_deterministic_budget(self) -> None:
        limits = SearchLimits(max_work_units=4_000)
        bible = self._bible(limits)

        for query, expected_total in (("神", 5), ("神爱", 2)):
            with self.subTest(query=query):
                response = bible.search(
                    query,
                    "multi",
                    SearchBible(match="substring"),
                )
                self.assertEqual(response["query"]["total"], expected_total)
                self.assertLessEqual(
                    response["query"]["cost"]["work_units"],
                    limits.max_work_units,
                )

    def test_many_continuous_terms_stay_inside_a_tight_budget(self) -> None:
        # Under 1.x this query forced a vocabulary scan per term and was
        # rejected. Positional postings answer it exactly and cheaply, so it
        # now succeeds well inside the same budget.
        limits = SearchLimits(max_work_units=4_000)
        bible = self._bible(limits)
        bible.warm_translation("multi")
        query = "神 爱 天 地 起 初 生 命 道 光 日 月 人 子 王 国"

        response = bible.search(query, "multi", SearchBible(words="any"))

        self.assertEqual(response["query"]["total"], 5)
        self.assertLessEqual(
            response["query"]["cost"]["work_units"], limits.max_work_units
        )

    def test_an_unusable_work_budget_is_refused_before_an_index_is_built(
        self,
    ) -> None:
        bible = self._bible(SearchLimits(max_work_units=1))

        with self.assertRaisesRegex(SearchLimitError, "configured maximum"):
            bible.search("神", "multi")


if __name__ == "__main__":
    unittest.main()
