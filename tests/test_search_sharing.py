"""Corpus sharing and index construction under concurrency."""

import tempfile
import threading
import unittest
from pathlib import Path

from getbible import GetBible, SearchBible
from getbible.search import CorpusRegistry, shared_registry
from getbible.search.corpus import TranslationCorpus
from getbible.translation_cache import TranslationSnapshot

FIXTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "multilingual_repository"


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

    def test_an_index_build_is_not_charged_to_the_request_deadline(self) -> None:
        # deadline_seconds governs one request; index_build_seconds governs a
        # build that every later request benefits from.
        from getbible.search import SearchLimits

        limits = SearchLimits(deadline_seconds=0.001, index_build_seconds=60.0)
        corpus = TranslationCorpus(_snapshot())

        index = corpus.index(False, True, limits)

        self.assertGreater(len(index.postings), 0)

    def test_a_built_index_is_published_before_the_lock_is_released(self) -> None:
        corpus = TranslationCorpus(_snapshot())

        first = corpus.index()

        self.assertIs(corpus.index(), first)
        self.assertEqual(len(corpus.cache_info()["indexes"]), 1)


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
