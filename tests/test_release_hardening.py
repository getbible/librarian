import hashlib
import json
import shutil
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from getbible import (
    CacheIntegrityError,
    GetBible,
    RepositoryResponseError,
    SearchBible,
    SearchDeadlineExceeded,
    SearchLimitError,
    SearchLimits,
    SearchValidationError,
    TranslationNotFoundError,
)

FIXTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "repository"


class ReleaseHardeningTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        shutil.copytree(FIXTURE_REPOSITORY, self.repository)
        self.cache = self.root / "cache"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _bible(self, **kwargs: object) -> GetBible:
        bible = GetBible(
            repo_path=self.repository,
            cache_dir=self.cache,
            **kwargs,
        )
        self.addCleanup(bible.close)
        return bible

    def _publish_translation_sha(self) -> str:
        translation = self.repository / "v2" / "test.json"
        checksum = hashlib.sha1(translation.read_bytes()).hexdigest()
        (translation.parent / "test.sha").write_text(checksum, encoding="utf-8")
        return checksum

    def test_missing_search_and_warm_never_enter_translation_cache(self) -> None:
        bible = self._bible()
        with patch.object(bible._translation_cache, "load") as load:
            for operation in (
                lambda: bible.search("faith", "missing"),
                lambda: bible.warm_translation("missing"),
            ):
                with self.assertRaises(TranslationNotFoundError):
                    operation()
        load.assert_not_called()
        self.assertEqual(bible.cache_info()["negative_translations"]["size"], 1)

    def test_invalid_nested_refresh_preserves_last_known_good_corpus(self) -> None:
        self._publish_translation_sha()
        bible = self._bible(cache_ttl=timedelta(seconds=0))
        first = bible.search("faith", "test")

        translation_path = self.repository / "v2" / "test.json"
        invalid = json.loads(translation_path.read_text(encoding="utf-8"))
        invalid["books"][0]["chapters"][0]["verses"][0]["chapter"] = 999
        translation_path.write_text(json.dumps(invalid), encoding="utf-8")
        self._publish_translation_sha()

        second = bible.search("faith", "test")
        self.assertEqual(second["query"]["sha"], first["query"]["sha"])
        self.assertTrue(second["query"]["cache"]["stale"])

    def test_books_index_mismatch_is_rejected_before_cache_commit(self) -> None:
        books_path = self.repository / "v2" / "test" / "books.json"
        books = json.loads(books_path.read_text(encoding="utf-8"))
        books["1"]["name"] = "Not Genesis"
        books_path.write_text(json.dumps(books), encoding="utf-8")
        bible = self._bible()

        with self.assertRaises(CacheIntegrityError):
            bible.search("faith", "test")
        metadata = tuple(self.cache.rglob("test.metadata.json"))
        self.assertEqual(metadata, ())

    def test_validated_payload_is_content_addressed_and_versioned(self) -> None:
        sha = self._publish_translation_sha()
        bible = self._bible(require_checksums=True)
        bible.search("faith", "test")

        metadata_path = next(self.cache.rglob("test.metadata.json"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["validation_version"], 2)
        self.assertEqual(metadata["sha"], sha)
        self.assertEqual(metadata["payload"], f"{sha}.json")
        self.assertEqual(metadata["source_generation"], 0)
        self.assertTrue((metadata_path.parent / "objects" / f"{sha}.json").is_file())

    def test_required_full_and_chapter_checksums_fail_closed(self) -> None:
        bible = self._bible(require_checksums=True)
        with self.assertRaisesRegex(RepositoryResponseError, "required checksum"):
            bible.search("faith", "test")
        with self.assertRaisesRegex(RepositoryResponseError, "required checksum"):
            bible.select("1 1:1", "test")

        chapter = self.repository / "v2" / "test" / "1" / "1.json"
        chapter.with_suffix(".sha").write_text("0" * 40, encoding="utf-8")
        optional = self._bible(require_checksums=False)
        with self.assertRaises(CacheIntegrityError):
            optional.select("1 1:1", "test")

    def test_select_and_search_results_do_not_mutate_cached_data(self) -> None:
        bible = self._bible()
        selected = bible.select("1 1:1", "test")
        selected["test_1_1"]["translation"] = "mutated"
        selected["test_1_1"]["verses"][0]["text"] = "mutated"
        selected_again = bible.select("1 1:1", "test")["test_1_1"]
        self.assertEqual(selected_again["translation"], "Librarian Test Translation")
        self.assertNotEqual(selected_again["verses"][0]["text"], "mutated")

        searched = bible.search("faith", "test")
        searched["query"]["translation"]["translation"] = "mutated"
        searched["results"]["test_1_1"]["verses"][0]["text"] = "mutated"
        searched_again = bible.search("faith", "test")
        self.assertEqual(
            searched_again["query"]["translation"]["translation"],
            "Librarian Test Translation",
        )
        self.assertNotEqual(
            searched_again["results"]["test_1_1"]["verses"][0]["text"],
            "mutated",
        )

    def test_expensive_classification_and_substring_minimum_are_pre_execution(self) -> None:
        self.assertTrue(SearchBible(match="substring").expensive)
        self.assertFalse(SearchBible().expensive)
        bible = self._bible()
        with (
            patch.object(bible._translation_cache, "load") as load,
            self.assertRaises(SearchValidationError),
        ):
            bible.search("a", "test", SearchBible(match="substring"))
        load.assert_not_called()

    def test_work_response_and_deadline_budgets_are_enforced(self) -> None:
        work_limited = self._bible(search_limits=SearchLimits(max_work_units=1))
        with (
            patch("getbible.search.TranslationCorpus.index") as build_index,
            self.assertRaises(SearchLimitError),
        ):
            work_limited.search("faith", "test")
        build_index.assert_not_called()

        response_limited = self._bible(
            search_limits=SearchLimits(max_response_bytes=100)
        )
        with self.assertRaises(SearchLimitError):
            response_limited.search("faith", "test")

        deadline_limited = self._bible(
            search_limits=SearchLimits(
                deadline_seconds=0.001,
                deadline_check_interval=1,
            )
        )
        with (
            patch(
                "getbible.search.SearchBudget.checkpoint",
                side_effect=SearchDeadlineExceeded("deadline"),
            ),
            self.assertRaises(SearchDeadlineExceeded),
        ):
            deadline_limited.search("faith", "test")

    def test_generation_transition_invalidates_other_workers(self) -> None:
        first = self._bible()
        second = self._bible()
        first.search("faith", "test")
        second.search("faith", "test")
        self.assertEqual(second.cache_info()["search_corpora"]["size"], 1)

        calls: list[tuple[int, int]] = []
        transitioned = first.transition_source(
            "mirror-2026-07-20",
            lambda old, new: calls.append((old.generation, new.generation)),
        )
        self.assertEqual(calls, [(0, 1)])
        self.assertEqual(transitioned["generation"], 1)

        with second.source_operation() as generation:
            self.assertEqual(generation.generation, 1)
            self.assertTrue(generation.cache_namespace.endswith(":g1"))
        self.assertEqual(second.cache_info()["search_corpora"]["size"], 0)
        self.assertEqual(second.cache_info()["negative_translations"]["size"], 0)

        translation_path = self.repository / "v2" / "test.json"
        translation = json.loads(translation_path.read_text(encoding="utf-8"))
        translation["books"][0]["chapters"][0]["verses"][0]["text"] = (
            "Beacon comes by hearing."
        )
        translation_path.write_text(json.dumps(translation), encoding="utf-8")
        self.assertEqual(second.search("beacon", "test")["query"]["total"], 1)
        metadata_path = next(self.cache.rglob("test.metadata.json"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_generation"], 1)

    def test_transition_waits_for_a_reader_that_started_before_first_manifest(self) -> None:
        first = self._bible()
        second = self._bible()
        entered = threading.Event()
        release = threading.Event()
        purged = threading.Event()

        def read_source() -> None:
            with first.source_operation():
                entered.set()
                self.assertTrue(release.wait(2))

        with ThreadPoolExecutor(max_workers=2) as executor:
            reader = executor.submit(read_source)
            self.assertTrue(entered.wait(2))
            transition = executor.submit(
                second.transition_source,
                "after-reader",
                lambda *_: purged.set(),
            )
            self.assertFalse(purged.wait(0.05))
            release.set()
            reader.result(timeout=2)
            state = transition.result(timeout=2)

        self.assertTrue(purged.is_set())
        self.assertEqual(state["generation"], 1)

    def test_failed_or_duplicate_generation_purge_cannot_partially_commit(self) -> None:
        first = self._bible()
        second = self._bible()

        def fail(*_: object) -> None:
            raise RuntimeError("purge failed")

        with self.assertRaisesRegex(RuntimeError, "purge failed"):
            first.transition_source("broken", fail)
        self.assertEqual(first.cache_info()["source"]["generation"], 0)

        calls = 0
        guard = threading.Lock()

        def purge(*_: object) -> None:
            nonlocal calls
            with guard:
                calls += 1
            time.sleep(0.01)

        with ThreadPoolExecutor(max_workers=2) as executor:
            states = list(
                executor.map(
                    lambda bible: bible.transition_source("stable", purge),
                    (first, second),
                )
            )
        self.assertEqual(calls, 1)
        self.assertEqual({state["generation"] for state in states}, {1})


if __name__ == "__main__":
    unittest.main()
