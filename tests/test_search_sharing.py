"""Corpus sharing and index construction under concurrency."""

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from getbible import GetBible, SearchBible, SearchDeadlineExceeded
from getbible.search import (
    CorpusRegistry,
    SearchBudget,
    SearchEngine,
    SearchLimits,
    shared_registry,
)
from getbible.search.corpus import TranslationCorpus
from getbible.translation_cache import TranslationSnapshot

FIXTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "multilingual_repository"


class _FakeClock:
    """Thread-safe monotonic clock advanced explicitly by each test phase."""

    def __init__(self, value: float = 0.0) -> None:
        self._lock = threading.Lock()
        self._value = value

    def __call__(self) -> float:
        with self._lock:
            return self._value

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._value += seconds


class _ObservedLock:
    """Lock that records when a second caller has to wait for its holder."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.waiting = threading.Event()

    def __enter__(self) -> "_ObservedLock":
        if not self._lock.acquire(blocking=False):
            self.waiting.set()
            if not self._lock.acquire(timeout=2.0):
                raise TimeoutError("Timed out waiting for the test index lock.")
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._lock.release()


def _snapshot(sha: str = "sha-one") -> TranslationSnapshot:
    return TranslationSnapshot(
        data={
            "translation": "Test",
            "abbreviation": "t",
            "lang": "en",
            "language": "English",
            "direction": "LTR",
            "encoding": "UTF-8",
            "books": [
                {
                    "nr": 1,
                    "name": "Book",
                    "chapters": [
                        {
                            "chapter": 1,
                            "name": "Book 1",
                            "verses": [
                                {
                                    "chapter": 1,
                                    "verse": number,
                                    "name": f"Book 1:{number}",
                                    "text": f"faith and hope number {number}",
                                }
                                for number in range(1, 40)
                            ],
                        }
                    ],
                }
            ],
        },
        sha=sha,
        checked_at=0.0,
        stale=False,
    )


class TestCorpusSharing(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def _bible(self) -> GetBible:
        bible = GetBible(repo_path=FIXTURE_REPOSITORY, cache_dir=self.temporary.name)
        self.addCleanup(bible.close)
        return bible

    def test_separate_clients_share_one_corpus_and_one_index(self) -> None:
        # A service that constructs a client per request, or holds several for
        # different configurations, must not re-parse and re-analyse a
        # translation each time. Sharing is what makes that free.
        first, second = self._bible(), self._bible()

        corpus_a = first._search_corpus("multi")
        corpus_b = second._search_corpus("multi")

        self.assertIs(corpus_a, corpus_b)
        self.assertIs(corpus_a.index(), corpus_b.index())

    def test_searches_from_separate_clients_agree(self) -> None:
        first, second = self._bible(), self._bible()

        self.assertEqual(
            first.search("神", "multi")["query"]["total"],
            second.search("神", "multi")["query"]["total"],
        )

    def test_a_changed_source_sha_does_not_reuse_stale_verses(self) -> None:
        registry = CorpusRegistry()

        original = registry.acquire("repo", "t", _snapshot("sha-one"))
        replaced = registry.acquire("repo", "t", _snapshot("sha-two"))

        self.assertIsNot(original, replaced)
        self.assertEqual(replaced.sha, "sha-two")

    def test_repositories_are_kept_apart(self) -> None:
        registry = CorpusRegistry()

        one = registry.acquire("repo-a", "t", _snapshot())
        two = registry.acquire("repo-b", "t", _snapshot())

        self.assertIsNot(one, two)

    def test_the_registry_is_bounded(self) -> None:
        registry = CorpusRegistry(limit=2)

        for index in range(5):
            registry.acquire("repo", f"t{index}", _snapshot(f"sha-{index}"))

        self.assertEqual(registry.info()["entries"], 2)
        self.assertEqual(registry.info()["evictions"], 3)

    def test_the_shared_registry_is_one_object_per_process(self) -> None:
        self.assertIs(shared_registry(), shared_registry())


class TestIndexConstruction(unittest.TestCase):
    def test_concurrent_first_requests_build_the_index_once(self) -> None:
        # The first requests to arrive must not each build their own copy, and
        # none of them may be charged for the build: an abandoned build caches
        # nothing, so the next request repeats it and fails the same way.
        corpus = TranslationCorpus(_snapshot())
        builds = 0
        original = corpus.index
        guard = threading.Lock()

        indexes: list[object] = []

        def build() -> None:
            indexes.append(original())

        threads = [threading.Thread(target=build) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        with guard:
            builds = len({id(value) for value in indexes})
        self.assertEqual(builds, 1)
        self.assertEqual(len(indexes), 8)

    def test_a_built_index_is_published_before_the_lock_is_released(self) -> None:
        corpus = TranslationCorpus(_snapshot())

        first = corpus.index()

        self.assertIs(corpus.index(), first)
        self.assertEqual(len(corpus.cache_info()["indexes"]), 1)


class TestSearchDeadlineAccounting(unittest.TestCase):
    def _engine(
        self,
        corpus: TranslationCorpus,
        limits: SearchLimits,
    ) -> SearchEngine:
        return SearchEngine(
            corpus,
            lambda name: 1 if name == "Book" else None,
            limits,
        )

    def test_cold_index_time_is_excluded_end_to_end(self) -> None:
        from getbible.search import corpus as corpus_module

        clock = _FakeClock()
        limits = SearchLimits(deadline_seconds=5.0, index_build_seconds=60.0)
        corpus = TranslationCorpus(_snapshot())
        engine = self._engine(corpus, limits)
        original = corpus_module.build_index
        build_calls = 0

        def delayed_build(*args: object, **kwargs: object) -> object:
            nonlocal build_calls
            build_calls += 1
            clock.advance(10.0)
            return original(*args, **kwargs)

        with (
            patch("getbible.search.limits.time.monotonic", clock),
            patch.object(corpus_module, "build_index", delayed_build),
        ):
            hits, total = engine.search("faith", SearchBible())

        self.assertEqual(build_calls, 1)
        self.assertEqual(total, 39)
        self.assertEqual(len(hits), 39)
        self.assertEqual(engine.execution_info["elapsed_seconds"], 0.0)

    def test_warm_index_does_not_reset_request_owned_work(self) -> None:
        clock = _FakeClock()
        limits = SearchLimits(deadline_seconds=5.0, index_build_seconds=60.0)
        corpus = TranslationCorpus(_snapshot())
        corpus.index(False, True, limits)
        engine = self._engine(corpus, limits)
        original_book_filter = engine._book_filter
        original_resolve = engine._resolve

        def delayed_book_filter(criteria: SearchBible) -> frozenset[int]:
            clock.advance(3.0)
            return original_book_filter(criteria)

        def delayed_resolve(*args: object, **kwargs: object) -> object:
            clock.advance(3.0)
            return original_resolve(*args, **kwargs)

        with (
            patch("getbible.search.limits.time.monotonic", clock),
            patch.object(engine, "_book_filter", side_effect=delayed_book_filter),
            patch.object(engine, "_resolve", side_effect=delayed_resolve),
            self.assertRaises(SearchDeadlineExceeded),
        ):
            engine.search("faith", SearchBible())

    def test_concurrent_builder_and_waiter_keep_their_request_deadlines(
        self,
    ) -> None:
        from getbible.search import corpus as corpus_module

        clock = _FakeClock()
        limits = SearchLimits(deadline_seconds=5.0, index_build_seconds=60.0)
        corpus = TranslationCorpus(_snapshot())
        index_lock = _ObservedLock()
        corpus._index_locks[(False, True)] = index_lock
        original = corpus_module.build_index
        build_started = threading.Event()
        release_build = threading.Event()
        build_calls = 0
        build_guard = threading.Lock()

        def blocked_build(*args: object, **kwargs: object) -> object:
            nonlocal build_calls
            with build_guard:
                build_calls += 1
            build_started.set()
            if not release_build.wait(timeout=2.0):
                raise TimeoutError("Timed out waiting to release the test build.")
            clock.advance(10.0)
            return original(*args, **kwargs)

        def search() -> tuple[int, int]:
            hits, total = self._engine(corpus, limits).search(
                "faith", SearchBible()
            )
            return len(hits), total

        with (
            patch("getbible.search.limits.time.monotonic", clock),
            patch.object(corpus_module, "build_index", blocked_build),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            futures = [executor.submit(search) for _ in range(2)]
            started = build_started.wait(timeout=2.0)
            waiting = index_lock.waiting.wait(timeout=2.0) if started else False
            release_build.set()
            results = [future.result(timeout=2.0) for future in futures]

        self.assertTrue(started)
        self.assertTrue(waiting)
        self.assertEqual(build_calls, 1)
        self.assertEqual(results, [(39, 39), (39, 39)])
        self.assertEqual(len(corpus.cache_info()["indexes"]), 1)

    def test_index_build_limit_remains_independent(self) -> None:
        from getbible.search import corpus as corpus_module

        clock = _FakeClock()
        limits = SearchLimits(deadline_seconds=5.0, index_build_seconds=1.0)
        corpus = TranslationCorpus(_snapshot())
        engine = self._engine(corpus, limits)

        def overdue_build(
            texts: object,
            analyzer: object,
            checkpoint: object,
        ) -> object:
            clock.advance(2.0)
            checkpoint(0)
            self.fail("The overdue index build should have been stopped.")

        with (
            patch("getbible.search.limits.time.monotonic", clock),
            patch.object(corpus_module, "build_index", overdue_build),
            self.assertRaisesRegex(TimeoutError, "Index construction exceeded"),
        ):
            engine.search("faith", SearchBible())

        self.assertEqual(corpus.cache_info()["indexes"], [])

    def test_extending_a_budget_preserves_own_work_and_telemetry(self) -> None:
        clock = _FakeClock(100.0)
        limits = SearchLimits(deadline_seconds=5.0)

        with patch("getbible.search.limits.time.monotonic", clock):
            budget = SearchBudget(limits)
            clock.advance(2.5)
            budget.extend(2.5)

            self.assertEqual(budget.started_at, 102.5)
            self.assertEqual(budget.deadline, 107.5)
            self.assertEqual(budget.elapsed_seconds, 0.0)

            budget.extend(0.0)
            budget.extend(-1.0)
            self.assertEqual(budget.started_at, 102.5)
            self.assertEqual(budget.deadline, 107.5)

            clock.advance(1.25)
            self.assertEqual(budget.elapsed_seconds, 1.25)


class TestSharedCorpusStillHonoursCriteria(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.bible = GetBible(
            repo_path=FIXTURE_REPOSITORY, cache_dir=self.temporary.name
        )
        self.addCleanup(self.bible.close)

    def test_each_analysis_policy_gets_its_own_index(self) -> None:
        self.bible.search("神", "multi", SearchBible())
        self.bible.search("神", "multi", SearchBible(diacritics="exact"))
        self.bible.search("神", "multi", SearchBible(case_sensitive=True))

        corpus = self.bible._search_corpus("multi")

        self.assertEqual(len(corpus.cache_info()["indexes"]), 3)


if __name__ == "__main__":
    unittest.main()
