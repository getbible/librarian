import json
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from getbible import (
    CacheIntegrityError,
    GetBible,
    SearchCriteria,
    SearchValidationError,
)

FIXTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "repository"


class TestSearchCriteria(unittest.TestCase):
    def test_mapping_is_json_friendly(self):
        criteria = SearchCriteria.from_value(
            {
                "words": "phrase",
                "match": "substring",
                "books": ["Genesis", 40],
                "exclude": ["darkness"],
                "limit": 25,
            }
        )
        self.assertEqual(criteria.words, "phrase")
        self.assertEqual(criteria.books, ("Genesis", 40))
        self.assertEqual(criteria.to_dict()["books"], ["Genesis", 40])

    def test_legacy_criteria_are_supported(self):
        criteria = SearchCriteria.from_legacy(
            "allwords-exactmatch-caseinsensitive-newtestament"
        )
        self.assertEqual(criteria.words, "all")
        self.assertEqual(criteria.match, "whole_word")
        self.assertFalse(criteria.case_sensitive)
        self.assertEqual(criteria.scope, "new_testament")

    def test_unknown_criterion_is_rejected(self):
        with self.assertRaises(SearchValidationError):
            SearchCriteria.from_value({"unknown": True})

    def test_single_book_and_exclusion_strings_are_normalized(self):
        criteria = SearchCriteria(books="Genesis", exclude="darkness")
        self.assertEqual(criteria.books, ("Genesis",))
        self.assertEqual(criteria.exclude, ("darkness",))

    def test_non_string_modes_are_rejected_cleanly(self):
        with self.assertRaises(SearchValidationError):
            SearchCriteria.from_value({"words": 1})

    def test_invalid_pagination_is_rejected(self):
        with self.assertRaises(SearchValidationError):
            SearchCriteria(limit=0)
        with self.assertRaises(SearchValidationError):
            SearchCriteria(offset=-1)


class TestGetBibleSearch(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.bible = GetBible(
            repo_path=str(FIXTURE_REPOSITORY),
            cache_dir=self.temporary.name,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_phrase_search_preserves_scripture_contract(self):
        response = self.bible.search(
            "in the beginning",
            "test",
            SearchCriteria(words="phrase"),
        )
        self.assertEqual(response["query"]["total"], 1)
        self.assertEqual(response["query"]["returned"], 1)
        self.assertFalse(response["query"]["has_more"])
        self.assertEqual(response["matches"][0]["reference"], "Genesis 1:1")
        result = response["results"]["test_1_1"]
        self.assertEqual(result["translation"], "Librarian Test Translation")
        self.assertEqual(result["book_nr"], 1)
        self.assertEqual(result["chapter"], 1)
        self.assertEqual(result["ref"], ["Genesis 1:1"])
        self.assertEqual(
            result["verses"][0],
            self.bible.select("1 1:1", "test")["test_1_1"]["verses"][0],
        )

    def test_all_and_any_word_modes(self):
        all_response = self.bible.search("faith hope", "test")
        any_response = self.bible.search(
            "faith wisdom", "test", SearchCriteria(words="any")
        )
        self.assertEqual(all_response["query"]["total"], 3)
        self.assertEqual(any_response["query"]["total"], 4)

    def test_whole_word_and_substring_modes(self):
        whole = self.bible.search("great", "test")
        partial = self.bible.search(
            "great", "test", SearchCriteria(match="substring")
        )
        self.assertEqual(whole["query"]["total"], 0)
        self.assertEqual(partial["query"]["total"], 1)

    def test_case_sensitive_mode(self):
        sensitive = self.bible.search(
            "Word", "test", SearchCriteria(case_sensitive=True)
        )
        insensitive = self.bible.search("word", "test")
        self.assertEqual(sensitive["matches"][0]["occurrences"], 1)
        self.assertEqual(insensitive["matches"][0]["occurrences"], 2)

    def test_testament_and_deuterocanonical_scopes(self):
        old = self.bible.search(
            "faith hope", "test", SearchCriteria(scope="old_testament")
        )
        new = self.bible.search(
            "faith hope", "test", SearchCriteria(scope="new_testament")
        )
        deuterocanon = self.bible.search(
            "wisdom", "test", SearchCriteria(scope="deuterocanon")
        )
        self.assertEqual(old["query"]["total"], 1)
        self.assertEqual(new["query"]["total"], 2)
        self.assertEqual(deuterocanon["matches"][0]["book_nr"], 67)

    def test_specific_books_accept_names_and_numbers(self):
        by_name = self.bible.search(
            "faith hope", "test", SearchCriteria(books=("Genesis",))
        )
        by_number = self.bible.search(
            "faith hope", "test", SearchCriteria(books=(40,))
        )
        self.assertEqual(by_name["query"]["total"], 1)
        self.assertEqual(by_number["query"]["total"], 2)

    def test_diacritic_insensitive_search(self):
        sensitive = self.bible.search("Cafe", "test")
        insensitive = self.bible.search(
            "Cafe", "test", SearchCriteria(diacritics="insensitive")
        )
        self.assertEqual(sensitive["query"]["total"], 0)
        self.assertEqual(insensitive["query"]["total"], 1)

    def test_exclusion_and_proximity(self):
        excluded = self.bible.search(
            "faith hope", "test", SearchCriteria(exclude=("love",))
        )
        adjacent = self.bible.search(
            "faith hope", "test", SearchCriteria(proximity=0)
        )
        self.assertEqual(excluded["query"]["total"], 2)
        self.assertEqual(adjacent["query"]["total"], 1)
        self.assertEqual(adjacent["matches"][0]["reference"], "Genesis 1:3")

    def test_pagination_and_relevance_metadata(self):
        response = self.bible.search(
            "faith hope",
            "test",
            SearchCriteria(sort="relevance", limit=1, offset=1),
        )
        self.assertEqual(response["query"]["total"], 3)
        self.assertEqual(response["query"]["returned"], 1)
        self.assertTrue(response["query"]["has_more"])
        self.assertEqual(len(response["matches"]), 1)

    def test_search_json_matches_dictionary_output(self):
        criteria = SearchCriteria(scope="new_testament", limit=2)
        dictionary = self.bible.search("faith", "test", criteria)
        encoded = self.bible.search_json("faith", "test", criteria)
        self.assertEqual(json.loads(encoded), dictionary)

    def test_legacy_string_can_be_passed_directly(self):
        response = self.bible.search(
            "faith hope",
            "test",
            "allwords-exactmatch-caseinsensitive-newtestament",
        )
        self.assertEqual(response["query"]["total"], 2)

    def test_concurrent_searches_share_a_stable_corpus(self):
        def execute(_: int) -> tuple[int, str]:
            response = self.bible.search("faith hope", "test")
            return response["query"]["total"], response["query"]["sha"]

        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(execute, range(48)))
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(results[0][0], 3)

    def test_constructing_clients_does_not_create_threads(self):
        before = threading.active_count()
        clients = [
            GetBible(repo_path=str(FIXTURE_REPOSITORY), cache_dir=self.temporary.name)
            for _ in range(10)
        ]
        self.assertEqual(threading.active_count(), before)
        self.assertEqual(len(clients), 10)

    def test_invalid_translation_path_is_rejected(self):
        with self.assertRaises(ValueError):
            self.bible.search("faith", "../test")

    def test_missing_translation_uses_existing_file_not_found_contract(self):
        with self.assertRaisesRegex(FileNotFoundError, r"Translation \(missing\) not found"):
            self.bible.search("faith", "missing")


class TestTranslationCache(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        shutil.copytree(FIXTURE_REPOSITORY, self.repository)

    def tearDown(self):
        self.temporary.cleanup()

    def test_last_known_good_cache_is_served_when_source_disappears(self):
        bible = GetBible(
            repo_path=str(self.repository),
            cache_dir=str(self.root / "cache"),
            cache_ttl=timedelta(seconds=0),
        )
        first = bible.search("faith", "test")
        (self.repository / "v2" / "test.json").unlink()
        second = bible.search("faith", "test")
        self.assertEqual(first["query"]["sha"], second["query"]["sha"])
        self.assertTrue(second["query"]["cache"]["stale"])

    def test_mismatched_published_sha_is_rejected(self):
        (self.repository / "v2" / "test.sha").write_text("0" * 40, encoding="utf-8")
        bible = GetBible(
            repo_path=str(self.repository),
            cache_dir=str(self.root / "cache"),
        )
        with self.assertRaises(CacheIntegrityError):
            bible.search("faith", "test")


if __name__ == "__main__":
    unittest.main()
