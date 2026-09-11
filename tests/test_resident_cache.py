"""Offline cache lifecycle and retained-memory policy coverage."""

import hashlib
import json
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from getbible import GetBible
from getbible.search import CorpusRegistry, shared_registry

FIXTURE = Path(__file__).parent / "fixtures" / "repository"


class ResidentCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repository = self.root / "repository"
        shutil.copytree(FIXTURE, self.repository)
        self.bible = GetBible(
            repo_path=self.repository, cache_dir=self.root / "cache",
            cache_ttl=timedelta(days=30), cache_ttl_jitter=0,
        )
        self.addCleanup(self.bible.close)
        self.addCleanup(shared_registry().resize, 8, memory_bytes=None)

    def test_lazy_query_reuses_chapter_before_month_without_full_translation_read(self):
        self.bible.select("1 1:1", "test")
        with patch.object(
            self.bible._repository, "fetch_bytes", side_effect=AssertionError("cold")
        ):
            self.bible.select("1 1:1", "test")
        info = self.bible.cache_info()
        self.assertEqual(info["query_translations"]["test"]["chapters"], 1)
        self.assertEqual(info["translation_cache"]["downloads"], 0)
        self.assertEqual(info["ttl_seconds"], 30 * 86400)

    def test_ttl_rechecks_unchanged_sha_without_replacing_warm_corpus(self):
        raw = (self.repository / "v2/test.json").read_bytes()
        (self.repository / "v2/test.sha").write_text(hashlib.sha1(raw).hexdigest())
        original = self.bible._search_corpus("test")
        index = original.index()
        self.bible.configure_cache(cache_ttl=timedelta(0))
        with patch.object(
            self.bible._repository, "fetch_bytes", wraps=self.bible._repository.fetch_bytes
        ) as fetch:
            refreshed = self.bible._search_corpus("test")
        self.assertIs(original, refreshed)
        self.assertIs(index, refreshed.index())
        self.assertNotIn("test.json", [call.args[0] for call in fetch.call_args_list])

    def test_query_warming_populates_actual_selection_path_without_search_index(self):
        warmed = self.bible.warm_query("test")
        self.assertGreater(warmed["chapters"], 1)
        self.assertEqual(self.bible.cache_info()["search_corpora"]["size"], 0)
        with patch.object(
            self.bible._repository, "fetch_bytes", side_effect=AssertionError("cold")
        ):
            self.assertEqual(len(self.bible.select("1 1:1", "test")), 1)

    def test_targeted_query_warm_keeps_lightweight_path(self):
        self.bible.warm_query("test", references=["1 1:1"])
        self.assertEqual(self.bible.cache_info()["translation_cache"]["downloads"], 0)
        with self.assertRaises(TypeError):
            self.bible.warm_query("test", references="1 1:1")

    def test_cache_growth_preserves_existing_objects_and_freshness(self):
        original = self.bible._search_corpus("test")
        checked_at = original.checked_at
        self.bible.configure_cache(search_corpus_limit=100, shared_corpus_limit=100,
                                   translation_cache_limit=100, chapter_cache_limit=200000)
        self.assertIs(self.bible._search_corpus("test"), original)
        self.assertEqual(original.checked_at, checked_at)

    def test_configure_is_validated_before_any_setting_changes(self):
        with self.assertRaises(ValueError):
            self.bible.configure_cache(cache_ttl=timedelta(days=1), chapter_cache_bytes=-1)
        self.assertEqual(self.bible.cache_info()["ttl_seconds"], 30 * 86400)
        with self.assertRaises(ValueError):
            self.bible.configure_cache(shared_corpus_limit=None)
        with self.assertRaises(ValueError):
            self.bible.configure_cache(cache_ttl=timedelta(days=-1))

    def test_byte_limits_evict_retained_objects_but_allow_one_request_to_complete(self):
        self.bible.warm_query("test")
        self.bible.configure_cache(chapter_cache_bytes=1, translation_cache_bytes=1,
                                   shared_corpus_bytes=1)
        info = self.bible.cache_info()
        self.assertEqual(info["chapters"]["size"], 0)
        self.assertEqual(info["translation_cache"]["size"], 0)
        self.assertEqual(self.bible.search("faith", "test")["query"]["total"], 3)
        self.assertEqual(self.bible.cache_info()["search_corpora"]["size"], 0)
        self.assertEqual(self.bible.cache_info()["shared_registry"]["entries"], 0)

    def test_query_warm_reports_capacity_eviction_and_json_safe_estimates(self):
        self.bible.configure_cache(chapter_cache_limit=1)
        result = self.bible.warm_query("test")
        self.assertEqual(result["chapters"], 1)
        self.assertGreater(result["loaded"], result["chapters"])
        self.assertGreater(result["estimated_bytes"], 0)
        json.dumps(self.bible.cache_info(), allow_nan=False)

    def test_drop_clears_query_search_and_snapshot_but_not_source(self):
        self.bible.warm_query("test")
        self.bible.warm_translation("test")
        result = self.bible.drop_translation("test", disk=True)
        self.assertTrue(result["dropped"])
        info = self.bible.cache_info()
        self.assertNotIn("test", info["query_translations"])
        self.assertNotIn("test", info["search_corpora"]["translations"])
        self.assertNotIn("test", info["translation_cache"]["translations"])
        self.assertTrue((self.repository / "v2/test.json").exists())
        self.assertEqual(self.bible.select("1 1:1", "test")["test_1_1"]["verses"][0]["verse"], 1)

    def test_disk_drop_preserves_unrelated_translation_cache_objects(self):
        self.bible.warm_translation("test")
        paths = self.bible._translation_cache._paths("test")
        paths["objects"].mkdir()
        unrelated = paths["objects"] / "another-sha.json"
        unrelated.write_text("unrelated")
        self.bible.drop_translation("test", disk=True)
        self.assertEqual(unrelated.read_text(), "unrelated")

    def test_reload_forces_changed_translation_before_ttl(self):
        self.bible.warm_translation("test")
        path = self.repository / "v2/test.json"
        payload = json.loads(path.read_text())
        payload["books"][0]["chapters"][0]["verses"][0]["text"] = "distinctive replacement"
        path.write_text(json.dumps(payload))
        self.bible.reload_translation("test", target="both")
        self.assertEqual(self.bible.search("distinctive", "test")["query"]["total"], 1)
        self.assertEqual(
            self.bible.select("1 1:1", "test")["test_1_1"]["verses"][0]["text"],
            "distinctive replacement",
        )

    def test_source_transition_invalidates_query_residency(self):
        self.bible.warm_query("test")
        self.bible.transition_source("new-revision")
        self.assertEqual(self.bible.cache_info()["query_translations"], {})
        self.assertEqual(self.bible.cache_info()["translation_cache"]["source_generation"], 1)

    def test_drop_waits_for_inflight_source_reader(self):
        entered = threading.Event()
        release = threading.Event()

        def read():
            with self.bible.source_operation():
                entered.set()
                self.assertTrue(release.wait(5))

        with ThreadPoolExecutor(max_workers=2) as executor:
            reader = executor.submit(read)
            self.assertTrue(entered.wait(2))
            drop = executor.submit(self.bible.drop_translation, "test")
            self.assertFalse(drop.done())
            release.set()
            reader.result(timeout=2)
            self.assertTrue(drop.result(timeout=2)["dropped"])

    def test_registry_eviction_reuses_corpus_still_held_by_a_client(self):
        original = self.bible._search_corpus("test")
        shared_registry().resize(0)
        self.assertIs(self.bible._search_corpus("test"), original)
        self.assertEqual(shared_registry().info()["entries"], 0)

    def test_query_warm_does_not_extend_snapshot_freshness(self):
        self.bible.warm_translation("test")
        with patch("getbible.getbible.time.time", return_value=10**12):
            # Force a stable already-loaded snapshot so its original checked_at
            # can be compared to the explicit warm operation's clock.
            snapshot = self.bible._translation_cache._memory["test"]
            with patch.object(self.bible._translation_cache, "load", return_value=snapshot):
                self.bible.warm_query("test")
        info = self.bible.cache_info()["query_translations"]["test"]
        self.assertEqual(info["expired_chapters"], info["chapters"])

    def test_transition_between_synchronization_and_reader_lock_is_observed(self):
        self.bible.select("1 1:1", "test")
        other = GetBible(repo_path=self.repository, cache_dir=self.root / "cache")
        self.addCleanup(other.close)
        coordinator = self.bible._source_coordinator
        original = coordinator.synchronize
        transitioned = False

        def synchronize_then_transition():
            nonlocal transitioned
            state = original()
            if not transitioned:
                transitioned = True
                other.transition_source("concurrent-revision")
            return state

        with (
            patch.object(coordinator, "synchronize", side_effect=synchronize_then_transition),
            self.bible.source_operation() as source,
        ):
            self.assertEqual(source.generation, 1)
            self.assertEqual(self.bible.cache_info()["query_translations"], {})

    def test_registry_zero_and_invalid_limits(self):
        self.assertEqual(CorpusRegistry(limit=0).info()["limit"], 0)
        for invalid in (-1, True, 1.5):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                CorpusRegistry(limit=invalid)


if __name__ == "__main__":
    unittest.main()
