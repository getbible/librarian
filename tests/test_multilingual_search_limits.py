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
from getbible.search import _Matcher

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

    def test_combining_marks_cannot_pad_a_short_arabic_substring(self) -> None:
        bible = self._bible()

        with (
            patch.object(bible, "valid_translation") as valid_translation,
            patch.object(bible._translation_cache, "load") as load_translation,
            self.assertRaises(SearchValidationError),
        ):
            bible.search(
                "فِي",
                "multi",
                SearchBible(match="substring"),
            )

        valid_translation.assert_not_called()
        load_translation.assert_not_called()

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

    def test_public_helper_detects_continuous_writing_scripts(self) -> None:
        self.assertEqual(SEARCH_ENGINE_VERSION, 2)

        detected = {
            "Han": "神",
            "Hiragana": "め",
            "Katakana": "カー",
            "Thai": "ใน",
            "Lao": "ໃນ",
            "Khmer": "ការ",
            "Myanmar": "အစ",
            "Buginese": "ᨠᨱ",
        }
        not_detected = {
            "Hangul": "한글",
            "Arabic": "العربية",
            "Hebrew": "עברית",
            "Devanagari": "देव",
            "Latin": "faith",
        }

        for script, query in detected.items():
            with self.subTest(script=script):
                self.assertTrue(requires_substring_matching(query))
        for script, query in not_detected.items():
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

    def test_pathological_multiterm_scan_is_rejected_before_matching(self) -> None:
        limits = SearchLimits(max_work_units=4_000)
        bible = self._bible(limits)
        bible.warm_translation("multi")
        query = "神 爱 天 地 起 初 生 命 道 光 日 月 人 子 王 国"

        with (
            patch.object(_Matcher, "search", wraps=_Matcher.search) as match,
            self.assertRaisesRegex(SearchLimitError, "configured maximum"),
        ):
            bible.search(
                query,
                "multi",
                SearchBible(words="any", match="substring"),
            )

        match.assert_not_called()


if __name__ == "__main__":
    unittest.main()
