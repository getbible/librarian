"""A local repository is read in place: validated, held in memory, never
duplicated under the cache directory."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from getbible import GetBible

FIXTURE = Path(__file__).parent / "fixtures" / "repository"


class LocalRepositoryCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        shutil.copytree(FIXTURE, self.repository)
        self.cache_dir = self.root / "cache"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def client(self, **kwargs: object) -> GetBible:
        return GetBible(repo_path=str(self.repository), cache_dir=str(self.cache_dir), **kwargs)

    def metadata(self) -> dict:
        files = list(self.cache_dir.rglob("test.metadata.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text(encoding="utf-8"))

    def test_search_keeps_no_copy_of_a_local_translation(self) -> None:
        bible = self.client()
        try:
            response = bible.search("beginning", "test")
        finally:
            bible.close()
        self.assertEqual(response["query"]["total"], 1)
        self.assertEqual(self.metadata()["payload"], "source")
        self.assertEqual(list(self.cache_dir.rglob("objects/*")), [])

    def test_a_second_process_reuses_the_recorded_state(self) -> None:
        first = self.client()
        try:
            first.search("beginning", "test")
        finally:
            first.close()
        second = self.client()
        try:
            response = second.search("beginning", "test")
            info = second.cache_info()
        finally:
            second.close()
        self.assertEqual(response["query"]["total"], 1)
        self.assertEqual(self.metadata()["payload"], "source")
        self.assertGreaterEqual(info["translation_cache"]["disk_hits"], 1)
        self.assertEqual(list(self.cache_dir.rglob("objects/*")), [])

    def test_a_changed_source_is_reread_after_the_freshness_interval(self) -> None:
        bible = self.client(cache_ttl=timedelta(seconds=0))
        try:
            self.assertEqual(bible.search("beginning", "test")["query"]["total"], 1)
            translation_file = self.repository / "v2" / "test.json"
            data = json.loads(translation_file.read_text(encoding="utf-8"))
            verse = data["books"][0]["chapters"][0]["verses"][0]
            verse["text"] = verse["text"].replace("beginning", "start")
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            translation_file.write_bytes(raw)
            (self.repository / "v2" / "test.sha").write_text(hashlib.sha1(raw).hexdigest())
            self.assertEqual(bible.search("beginning", "test")["query"]["total"], 0)
            self.assertEqual(bible.search("start", "test")["query"]["total"], 1)
        finally:
            bible.close()
        self.assertEqual(self.metadata()["payload"], "source")
        self.assertEqual(list(self.cache_dir.rglob("objects/*")), [])

    def test_a_stale_recorded_sha_falls_back_to_a_fresh_read(self) -> None:
        bible = self.client()
        try:
            bible.search("beginning", "test")
        finally:
            bible.close()
        translation_file = self.repository / "v2" / "test.json"
        data = json.loads(translation_file.read_text(encoding="utf-8"))
        data["description"] = "changed underneath the recorded state"
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        translation_file.write_bytes(raw)
        (self.repository / "v2" / "test.sha").write_text(hashlib.sha1(raw).hexdigest())
        second = self.client()
        try:
            self.assertEqual(second.search("beginning", "test")["query"]["total"], 1)
        finally:
            second.close()
        self.assertEqual(self.metadata()["sha"], hashlib.sha1(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
