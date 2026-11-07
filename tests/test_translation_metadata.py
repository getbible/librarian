"""Public response contracts for the chapter API's translation metadata subset."""

import hashlib
import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from getbible import CacheIntegrityError, GetBible, SearchLimits
from getbible.translation_cache import TranslationCache

FIXTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "repository"
TRANSLATION_FIELDS = {
    "translation", "abbreviation", "lang", "language", "direction", "encoding",
}
CHAPTER_FIELDS = {"book_nr", "book_name", "chapter", "name", "ref", "verses"}


def nested_metadata(depth: int, leaf: object = "Published editorial text") -> object:
    value = leaf
    for level in range(depth):
        value = {"children": value} if level % 2 else [value]
    return value


class TestTranslationMetadataContract(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        shutil.copytree(FIXTURE_REPOSITORY, self.repository)
        self.translation_path = self.repository / "v2" / "test.json"
        self.chapter_path = self.repository / "v2" / "test" / "1" / "1.json"
        self.source = json.loads(self.translation_path.read_text(encoding="utf-8"))
        self.metadata = {field: self.source[field] for field in TRANSLATION_FIELDS}
        self.extra_metadata = {
            "description": "A translation description which belongs in the metadata API.",
            "history": {"editions": [{"year": 2026, "notes": ["original", "revised"]}]},
            "distribution_license": "Distribution terms from the source translation.",
            "distribution_versification": "Fixture versification",
            "source": "Fixture publisher",
            "future_metadata": {"nested": ["Must never enter a scripture response."]},
        }
        self.source.update(self.extra_metadata)
        self.source["books"][0]["chapters"][0]["verses"][2]["footnote"] = "A verse annotation."
        self._write(self.translation_path, self.source)
        for book in self.source["books"]:
            for chapter in book["chapters"]:
                path = self.repository / "v2" / "test" / str(book["nr"]) / "1.json"
                path.parent.mkdir(exist_ok=True)
                self._write(path, {
                    **self.metadata,
                    **self.extra_metadata,
                    "book_nr": book["nr"],
                    "book_name": book["name"],
                    **chapter,
                })

    @staticmethod
    def _write(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def _bible(self, **kwargs: object) -> GetBible:
        bible = GetBible(
            repo_path=self.repository,
            cache_dir=self.root / "cache",
            **kwargs,
        )
        self.addCleanup(bible.close)
        return bible

    def _assert_chapter(self, chapter: dict, metadata: dict | None = None) -> None:
        expected = self.metadata if metadata is None else metadata
        self.assertEqual(set(chapter), set(expected) | CHAPTER_FIELDS)
        self.assertEqual({key: chapter[key] for key in expected}, expected)
        self.assertIsInstance(chapter["verses"], list)
        self.assertIsInstance(chapter["ref"], list)

    def _replace_metadata(self, **values: str) -> None:
        self.metadata.update(values)
        self.source.update(values)
        self._write(self.translation_path, self.source)
        books_path = self.repository / "v2" / "test" / "books.json"
        books = json.loads(books_path.read_text(encoding="utf-8"))
        for book in books.values():
            book.update(values)
        self._write(books_path, books)
        for path in self.repository.glob("v2/test/*/*.json"):
            chapter = json.loads(path.read_text(encoding="utf-8"))
            chapter.update(values)
            self._write(path, chapter)

    def test_search_and_search_json_return_only_six_translation_fields(self) -> None:
        bible = self._bible()
        response = bible.search("faith hope", "test")

        self.assertEqual(response["query"]["translation"], self.metadata)
        self.assertEqual(response["query"]["total"], 3)
        self.assertEqual(response["query"]["returned"], 3)
        self.assertEqual(set(response["results"]), {"test_1_1", "test_40_1"})
        self.assertEqual(len(response["matches"]), 3)
        for key, chapter in response["results"].items():
            self._assert_chapter(chapter)
            selected = bible.select(";".join(chapter["ref"]), "test")[key]
            self.assertEqual(chapter, selected)
        self.assertEqual(json.loads(bible.search_json("faith hope", "test")), response)

    def test_empty_search_results_still_have_only_six_translation_fields(self) -> None:
        response = self._bible().search("unfindableword", "test")

        self.assertEqual(response["query"]["translation"], self.metadata)
        self.assertEqual(response["query"]["total"], 0)
        self.assertEqual(response["results"], {})
        self.assertEqual(response["matches"], [])

    def test_cold_reference_results_filter_extra_chapter_metadata_without_full_load(self) -> None:
        bible = self._bible()
        reference = "Genesis 1:1-2;Genesis 1:2-3"
        with patch.object(bible._translation_cache, "load") as full_translation_load:
            selected = bible.select(reference, "test")
            encoded = bible.scripture(reference, "test")
        full_translation_load.assert_not_called()

        self.assertEqual(set(selected), {"test_1_1"})
        chapter = selected["test_1_1"]
        self._assert_chapter(chapter)
        self.assertEqual(chapter["book_nr"], 1)
        self.assertEqual(chapter["book_name"], "Genesis")
        self.assertEqual(chapter["chapter"], 1)
        self.assertEqual(chapter["name"], "Genesis 1")
        self.assertEqual(chapter["ref"], ["Genesis 1:1-2", "Genesis 1:2-3"])
        self.assertEqual(chapter["verses"], self.source["books"][0]["chapters"][0]["verses"][:3])
        self.assertEqual(json.loads(encoded), selected)

    def test_full_query_warming_matches_cold_chapter_results(self) -> None:
        bible = self._bible()
        reference = "Genesis 1:1-3;Matthew 1:2"
        cold = bible.select(reference, "test")
        warmed = bible.warm_query("test")

        self.assertEqual(warmed["loaded"], 3)
        # Serve the warmed chapter entries even when their source files vanish.
        for path in self.repository.glob("v2/test/*/*.json"):
            path.unlink()
        selected = bible.select(reference, "test")
        self.assertEqual(selected, cold)
        self.assertEqual(json.loads(bible.scripture(reference, "test")), cold)
        for chapter in selected.values():
            self._assert_chapter(chapter)

    def test_reference_query_warming_keeps_the_same_slim_contract(self) -> None:
        bible = self._bible()
        with patch.object(bible._translation_cache, "load") as full_translation_load:
            warmed = bible.warm_query("test", references=["Genesis 1:1"])
            chapter = bible.select("Genesis 1:1", "test")["test_1_1"]
        full_translation_load.assert_not_called()

        self.assertEqual(warmed["loaded"], 1)
        self._assert_chapter(chapter)

    def test_response_filtering_and_caller_mutation_leave_source_metadata_intact(self) -> None:
        bible = self._bible()
        snapshot = bible._translation_cache.load("test")
        original = deepcopy(snapshot.data)
        bible.warm_query("test")
        selected = bible.select("Genesis 1:3", "test")["test_1_1"]
        response = bible.search("faith", "test")
        selected["translation"] = "Changed by a caller"
        selected["history"] = {"injected": True}
        selected["verses"][0]["text"] = "Changed by a caller"
        response["query"]["translation"].update(selected="injected", translation="Changed")
        response["results"]["test_1_1"]["language"] = "Changed by a caller"
        response["results"]["test_1_1"]["verses"][0]["text"] = "Changed by a caller"

        self.assertEqual(snapshot.data, original)
        self.assertEqual(json.loads(self.translation_path.read_text(encoding="utf-8")), original)
        self.assertEqual(snapshot.data["history"], self.extra_metadata["history"])
        fresh_select = bible.select("Genesis 1:3", "test")["test_1_1"]
        fresh_search = bible.search("faith", "test")
        self._assert_chapter(fresh_select)
        self.assertEqual(fresh_search["query"]["translation"], self.metadata)
        self._assert_chapter(fresh_search["results"]["test_1_1"])
        self.assertEqual(fresh_select["verses"], [original["books"][0]["chapters"][0]["verses"][2]])
        self.assertEqual(fresh_search["results"]["test_1_1"]["verses"], fresh_select["verses"])

    def test_large_excluded_metadata_does_not_consume_search_response_budget(self) -> None:
        self.source["history"] = "Translation history. " * 4096
        self._write(self.translation_path, self.source)
        bible = self._bible(search_limits=SearchLimits(max_response_bytes=4096))

        response = bible.search("faith hope", "test")
        self.assertEqual(response["query"]["total"], 3)
        self.assertEqual(response["query"]["translation"], self.metadata)
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
        self.assertLessEqual(len(encoded.encode("utf-8")), 4096)

    def test_deep_editorial_survives_cold_warm_and_search_paths(self) -> None:
        for depth in (9, 72):
            with self.subTest(depth=depth):
                editorial = nested_metadata(depth)
                self.source["editorial"] = editorial
                for book in self.source["books"]:
                    book["editorial"] = editorial
                    for chapter in book["chapters"]:
                        chapter["editorial"] = editorial
                        for verse in chapter["verses"]:
                            verse["editorial"] = editorial
                        path = self.repository / "v2" / "test" / str(book["nr"]) / "1.json"
                        self._write(path, {
                            **self.metadata,
                            "book_nr": book["nr"],
                            "book_name": book["name"],
                            **chapter,
                        })
                self._write(self.translation_path, self.source)
                books_path = self.repository / "v2" / "test" / "books.json"
                books = json.loads(books_path.read_text(encoding="utf-8"))
                for book in books.values():
                    book["editorial"] = editorial
                self._write(books_path, books)

                bible = self._bible()
                cold = bible.select("Genesis 1:3", "test")["test_1_1"]
                snapshot = bible._translation_cache.load("test")
                self.assertEqual(snapshot.data, self.source)
                self.assertEqual(bible.warm_query("test")["loaded"], 3)
                warmed = bible.select("Genesis 1:3", "test")["test_1_1"]
                self.assertEqual(warmed, cold)
                bible.warm_translation("test")
                searched = bible.search("faith", "test")
                self.assertEqual(searched["query"]["translation"], self.metadata)
                for chapter in (cold, warmed, *searched["results"].values()):
                    self._assert_chapter(chapter)
                    for verse in chapter["verses"]:
                        self.assertEqual(verse["editorial"], editorial)
                self.assertEqual(snapshot.data, self.source)
                self.assertEqual(
                    json.loads(self.translation_path.read_text(encoding="utf-8")),
                    self.source,
                )
                bible.close()

    def test_depth_600_refresh_remains_usable_and_response_mutation_is_isolated(self) -> None:
        def publish_checksum(path: Path) -> str:
            checksum = hashlib.sha1(path.read_bytes(), usedforsecurity=False).hexdigest()
            path.with_suffix(".sha").write_text(checksum, encoding="utf-8")
            return checksum

        def annotation_leaf(value: object) -> dict:
            for _ in range(600):
                value = value["children"] if isinstance(value, dict) else value[0]
            return value

        initial_sha = publish_checksum(self.translation_path)
        bible = self._bible(cache_ttl=timedelta(seconds=0))
        self.assertEqual(bible.search("faith", "test")["query"]["sha"], initial_sha)
        original_verse = self.source["books"][0]["chapters"][0]["verses"][2]
        original_verse["editorial"] = nested_metadata(600, {"note": "Published annotation"})
        self._write(self.translation_path, self.source)
        chapter = json.loads(self.chapter_path.read_text(encoding="utf-8"))
        chapter["verses"][2]["editorial"] = original_verse["editorial"]
        self._write(self.chapter_path, chapter)
        refreshed_sha = publish_checksum(self.translation_path)
        publish_checksum(self.chapter_path)
        source_bytes = self.translation_path.read_bytes()
        self.assertNotEqual(refreshed_sha, initial_sha)

        # Refresh a previously usable cache, then exercise the same annotation
        # through cold references, warmed references, search and JSON wrappers.
        bible.warm_translation("test")
        snapshot = bible._translation_cache.load("test")
        self.assertEqual(snapshot.sha, refreshed_sha)
        self.assertFalse(snapshot.stale)
        bible.configure_cache(cache_ttl=timedelta(days=7))
        cold = bible.select("Genesis 1:3", "test")["test_1_1"]
        bible.warm_query("test")
        with patch.object(bible._repository, "fetch_bytes", side_effect=AssertionError(
            "Warmed references must use retained chapter data.",
        )):
            warmed = bible.select("Genesis 1:3", "test")["test_1_1"]
            scripture = json.loads(bible.scripture("Genesis 1:3", "test"))["test_1_1"]
        searched = bible.search("faith", "test")
        encoded_search = json.loads(bible.search_json("faith", "test"))
        self.assertEqual(searched["query"]["sha"], refreshed_sha)
        self.assertFalse(searched["query"]["cache"]["stale"])
        self.assertEqual(searched["query"]["translation"], self.metadata)

        for result in (
            cold, warmed, scripture, searched["results"]["test_1_1"],
            encoded_search["results"]["test_1_1"],
        ):
            self._assert_chapter(result)
            verse = next(item for item in result["verses"] if item["verse"] == 3)
            leaf = annotation_leaf(verse["editorial"])
            self.assertEqual(leaf, {"note": "Published annotation"})
            leaf["note"] = "Caller mutation"

        cached_verse = snapshot.data["books"][0]["chapters"][0]["verses"][2]
        self.assertEqual(annotation_leaf(cached_verse["editorial"]),
                         {"note": "Published annotation"})
        fresh = bible.select("Genesis 1:3", "test")["test_1_1"]["verses"][0]
        self.assertEqual(annotation_leaf(fresh["editorial"]), {"note": "Published annotation"})
        fresh_search = bible.search("faith", "test")["results"]["test_1_1"]["verses"]
        fresh = next(item for item in fresh_search if item["verse"] == 3)
        self.assertEqual(annotation_leaf(fresh["editorial"]), {"note": "Published annotation"})
        self.assertEqual(self.translation_path.read_bytes(), source_bytes)
        metadata_path = next((self.root / "cache").rglob("test.metadata.json"))
        self.assertEqual(json.loads(metadata_path.read_text())["sha"], refreshed_sha)

    def test_translation_and_language_strings_are_preserved_verbatim(self) -> None:
        self._replace_metadata(
            translation="Librarian Test Translation — full published name",
            language="English / Français / العربية",
            lang="en-Latn",
            direction="RTL",
        )
        bible = self._bible()

        response = bible.search("faith", "test")
        self.assertEqual(response["query"]["translation"], self.metadata)
        self._assert_chapter(response["results"]["test_1_1"])
        self._assert_chapter(bible.select("Genesis 1:3", "test")["test_1_1"])

    def test_accepted_empty_metadata_values_remain_present(self) -> None:
        self._replace_metadata(language="", encoding="")
        bible = self._bible()

        response = bible.search("faith", "test")
        self.assertEqual(response["query"]["translation"], self.metadata)
        self._assert_chapter(response["results"]["test_1_1"])
        self._assert_chapter(bible.select("Genesis 1:3", "test")["test_1_1"])

    def test_missing_chapter_metadata_is_not_fabricated(self) -> None:
        chapter = json.loads(self.chapter_path.read_text(encoding="utf-8"))
        for key in ("language", "encoding"):
            del chapter[key]
        self._write(self.chapter_path, chapter)
        expected = {key: value for key, value in self.metadata.items()
                    if key not in {"language", "encoding"}}

        self._assert_chapter(
            self._bible().select("Genesis 1:1", "test")["test_1_1"], expected,
        )


class TestMetadataTraversal(unittest.TestCase):
    def test_validation_does_not_use_the_python_recursion_stack(self) -> None:
        TranslationCache._validate_metadata_value(nested_metadata(1500), "editorial")

    def test_deep_invalid_values_still_fail_validation(self) -> None:
        invalid = (
            (float("nan"), "numeric ceiling"),
            (float("inf"), "numeric ceiling"),
            (TranslationCache.MAX_METADATA_INTEGER + 1, "numeric ceiling"),
            ({"": "invalid key"}, "invalid key"),
            (("unsupported tuple",), "unsupported value"),
        )
        for leaf, message in invalid:
            with (
                self.subTest(message=message, leaf=repr(leaf)),
                self.assertRaisesRegex(CacheIntegrityError, message),
            ):
                TranslationCache._validate_metadata_value(
                    nested_metadata(72, leaf), "editorial",
                )
        with (
            patch.object(TranslationCache, "MAX_TEXT_LENGTH", 3),
            self.assertRaisesRegex(CacheIntegrityError, "text ceiling"),
        ):
            TranslationCache._validate_metadata_value(
                nested_metadata(72, "long"), "editorial",
            )
        with (
            patch.object(TranslationCache, "MAX_METADATA_ITEMS", 3),
            self.assertRaisesRegex(CacheIntegrityError, "too many entries"),
        ):
            TranslationCache._validate_metadata_value(
                nested_metadata(72, [None] * 4), "editorial",
            )

    def test_cycles_are_rejected_but_shared_branches_are_accepted(self) -> None:
        cyclic_list: list = []
        cyclic_list.append(cyclic_list)
        cyclic_dict: dict = {}
        cyclic_dict["children"] = [cyclic_dict]
        for value in (cyclic_list, cyclic_dict):
            with (
                self.subTest(container=type(value).__name__),
                self.assertRaisesRegex(CacheIntegrityError, "cyclic value"),
            ):
                TranslationCache._validate_metadata_value(value, "editorial")

        shared = {"text": "Shared editorial text"}
        TranslationCache._validate_metadata_value([shared, shared], "editorial")


if __name__ == "__main__":
    unittest.main()
