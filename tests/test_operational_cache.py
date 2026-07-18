import json
import shutil
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from getbible import GetBible
from getbible._keyed_locks import KeyedLockPool

FIXTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "repository"


class OperationalCacheTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        shutil.copytree(FIXTURE_REPOSITORY, self.repository)
        self._clone_translation("test2")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _clone_translation(self, abbreviation: str) -> None:
        version = self.repository / "v2"
        translation = json.loads((version / "test.json").read_text(encoding="utf-8"))
        translation["abbreviation"] = abbreviation
        translation["translation"] = f"Translation {abbreviation}"
        (version / f"{abbreviation}.json").write_text(
            json.dumps(translation),
            encoding="utf-8",
        )

        source = json.loads((version / "test" / "books.json").read_text(encoding="utf-8"))
        for book in source.values():
            book["abbreviation"] = abbreviation
            book["translation"] = f"Translation {abbreviation}"
        target = version / abbreviation
        target.mkdir()
        (target / "books.json").write_text(json.dumps(source), encoding="utf-8")

    def test_warm_translation_builds_requested_index_without_a_query(self) -> None:
        bible = GetBible(
            repo_path=self.repository,
            cache_dir=self.root / "cache",
        )
        warmed = bible.warm_translation(
            "test",
            case_sensitive=True,
            diacritics="insensitive",
        )

        self.assertEqual(warmed["abbreviation"], "test")
        self.assertEqual(warmed["verses"], 9)
        self.assertEqual(
            warmed["indexes"],
            [{"case_sensitive": True, "diacritics": "insensitive"}],
        )
        self.assertIsInstance(json.dumps(bible.cache_info()), str)
        self.assertEqual(bible.cache_info()["active_resource_locks"], 0)

    def test_search_corpora_and_translation_snapshots_are_lru_bounded(self) -> None:
        bible = GetBible(
            repo_path=self.repository,
            cache_dir=self.root / "cache",
            search_corpus_limit=1,
            translation_cache_limit=1,
        )
        self.assertEqual(bible.search("faith", "test")["query"]["total"], 3)
        self.assertEqual(bible.search("faith", "test2")["query"]["total"], 3)

        info = bible.cache_info()
        self.assertEqual(info["search_corpora"]["size"], 1)
        self.assertEqual(info["search_corpora"]["evictions"], 1)
        self.assertEqual(list(info["search_corpora"]["translations"]), ["test2"])
        self.assertEqual(info["translation_cache"]["size"], 1)
        self.assertEqual(info["translation_cache"]["evictions"], 1)

        self.assertEqual(bible.search("faith", "test")["query"]["total"], 3)
        self.assertEqual(bible.cache_info()["active_resource_locks"], 0)

    def test_concurrent_eviction_does_not_invalidate_active_searches(self) -> None:
        bible = GetBible(
            repo_path=self.repository,
            cache_dir=self.root / "cache",
            search_corpus_limit=1,
            translation_cache_limit=1,
        )

        def execute(index: int) -> tuple[str, int]:
            code = "test" if index % 2 == 0 else "test2"
            return code, bible.search("faith", code)["query"]["total"]

        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(execute, range(48)))

        self.assertTrue(all(total == 3 for _, total in results))
        self.assertLessEqual(bible.cache_info()["search_corpora"]["size"], 1)
        self.assertEqual(bible.cache_info()["active_resource_locks"], 0)

    def test_books_cache_is_bounded_and_reports_hits(self) -> None:
        bible = GetBible(
            repo_path=self.repository,
            cache_dir=self.root / "cache",
            books_cache_limit=1,
        )
        self.assertTrue(bible.valid_translation("test"))
        self.assertTrue(bible.valid_translation("test"))
        self.assertTrue(bible.valid_translation("test2"))

        info = bible.cache_info()["books"]
        self.assertEqual(info["size"], 1)
        self.assertEqual(info["hits"], 1)
        self.assertEqual(info["evictions"], 1)

    def test_chapter_cache_is_bounded(self) -> None:
        source = json.loads(
            (self.repository / "v2" / "test.json").read_text(encoding="utf-8")
        )
        matthew = source["books"][1]["chapters"][0]
        chapter = {
            key: source[key]
            for key in (
                "translation",
                "abbreviation",
                "lang",
                "language",
                "direction",
                "encoding",
            )
        }
        chapter.update(
            {
                "book_nr": 40,
                "book_name": "Matthew",
                "chapter": 1,
                "name": matthew["name"],
                "verses": matthew["verses"],
            }
        )
        target = self.repository / "v2" / "test" / "40"
        target.mkdir()
        (target / "1.json").write_text(json.dumps(chapter), encoding="utf-8")

        bible = GetBible(
            repo_path=self.repository,
            cache_dir=self.root / "cache",
            chapter_cache_limit=1,
        )
        bible.select("1 1:1", "test")
        bible.select("40 1:1", "test")

        info = bible.cache_info()["chapters"]
        self.assertEqual(info["size"], 1)
        self.assertEqual(info["evictions"], 1)

    def test_zero_limits_disable_retention(self) -> None:
        bible = GetBible(
            repo_path=self.repository,
            cache_dir=self.root / "cache",
            reference_cache_limit=0,
            books_cache_limit=0,
            chapter_cache_limit=0,
            search_corpus_limit=0,
            translation_cache_limit=0,
        )
        bible.select("1 1:1", "test")
        bible.search("faith", "test")
        info = bible.cache_info()

        self.assertEqual(info["references"]["size"], 0)
        self.assertEqual(info["books"]["size"], 0)
        self.assertEqual(info["chapters"]["size"], 0)
        self.assertEqual(info["search_corpora"]["size"], 0)
        self.assertEqual(info["translation_cache"]["size"], 0)

    def test_invalid_cache_controls_fail_fast(self) -> None:
        for name in (
            "reference_cache_limit",
            "books_cache_limit",
            "chapter_cache_limit",
            "search_corpus_limit",
            "translation_cache_limit",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                GetBible(repo_path=self.repository, **{name: -1})
        with self.assertRaises(ValueError):
            GetBible(repo_path=self.repository, cache_ttl_jitter=1)

    def test_context_manager_closes_repository_sessions(self) -> None:
        bible = GetBible(repo_path=self.repository)
        with patch.object(bible._repository, "close") as close:
            with bible as opened:
                self.assertIs(opened, bible)
            close.assert_called_once_with()


class KeyedLockPoolTestCase(unittest.TestCase):
    def test_same_key_is_serialized_and_inactive_locks_are_removed(self) -> None:
        pool = KeyedLockPool()
        state_guard = threading.Lock()
        active = 0
        maximum_active = 0

        def execute(_: int) -> None:
            nonlocal active, maximum_active
            with pool.hold("translation:test"):
                with state_guard:
                    active += 1
                    maximum_active = max(maximum_active, active)
                time.sleep(0.001)
                with state_guard:
                    active -= 1

        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(execute, range(48)))

        self.assertEqual(maximum_active, 1)
        self.assertEqual(pool.size, 0)


if __name__ == "__main__":
    unittest.main()
