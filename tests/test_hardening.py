import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from getbible import (
    GetBible,
    GetBibleReference,
    ReferenceValidationError,
    RepositoryResponseTooLarge,
    RequestLimitError,
    RequestLimits,
    SearchValidationError,
    TranslationNotFoundError,
)
from getbible.repository_client import RepositoryClient


FIXTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "repository"


class TestReferenceHardening(unittest.TestCase):
    def setUp(self) -> None:
        self.references = GetBibleReference()

    def test_large_range_is_rejected_before_materialization(self) -> None:
        with self.assertRaises(RequestLimitError):
            self.references.ref("John 1:1-999999999", "kjv")

    def test_reversed_and_malformed_ranges_are_rejected(self) -> None:
        for reference in ("John 1:10-1", "John 1:16!", "John 1:1--2", "John 1:0"):
            with self.subTest(reference=reference):
                with self.assertRaises(ReferenceValidationError):
                    self.references.ref(reference, "kjv")

    def test_legacy_open_range_forms_remain_compatible(self) -> None:
        self.assertEqual(self.references.ref("John 1:2-", "kjv").verses, [2])
        self.assertEqual(self.references.ref("John 1:-5", "kjv").verses, [5])

    def test_cached_reference_cannot_be_mutated_by_a_caller(self) -> None:
        first = self.references.ref("John 1:1-3", "kjv")
        first.verses.append(999)
        second = self.references.ref("John 1:1-3", "kjv")
        self.assertEqual(second.verses, [1, 2, 3])

    def test_symbol_fuzz_is_fail_closed(self) -> None:
        generator = random.Random(20260718)
        symbols = "!@#$%^&*()[]{}<>?/\\|`~=+\x00\x01\x1f"
        for _ in range(500):
            value = "John 1:16" + "".join(generator.choice(symbols) for _ in range(3))
            self.assertFalse(self.references.valid(value, "kjv"), value)


class TestRequestBudgets(unittest.TestCase):
    def test_reference_count_is_rejected_before_repository_access(self) -> None:
        bible = GetBible(
            repo_path="/definitely/not/a/repository",
            request_limits=RequestLimits(max_references=1),
        )
        self.addCleanup(bible.close)
        with self.assertRaises(RequestLimitError):
            bible.select("John 1:1;John 1:2", "kjv")

    def test_total_verse_budget_is_enforced(self) -> None:
        bible = GetBible(
            repo_path=FIXTURE_REPOSITORY,
            request_limits=RequestLimits(
                max_references=2,
                max_verses_per_reference=3,
                max_total_verses=5,
            ),
        )
        self.addCleanup(bible.close)
        with self.assertRaises(RequestLimitError):
            bible.select("1 1:1-3;1 1:1-3", "test")

    def test_missing_translation_raises_typed_compatible_error(self) -> None:
        bible = GetBible(repo_path=FIXTURE_REPOSITORY)
        self.addCleanup(bible.close)
        with self.assertRaises(TranslationNotFoundError) as raised:
            bible.select("John 1:1", "missing")
        self.assertIsInstance(raised.exception, FileNotFoundError)

    def test_negative_translation_results_are_cached(self) -> None:
        bible = GetBible(repo_path=FIXTURE_REPOSITORY)
        self.addCleanup(bible.close)
        with patch(
            "getbible.hardened._BaseGetBible.valid_translation", return_value=False
        ) as validate:
            self.assertFalse(bible.valid_translation("missing"))
            self.assertFalse(bible.valid_translation("missing"))
        validate.assert_called_once_with("missing")
        self.assertEqual(bible.cache_info()["negative_translations"]["size"], 1)

    def test_invalid_search_is_rejected_before_repository_loading(self) -> None:
        bible = GetBible(repo_path="/definitely/not/a/repository")
        self.addCleanup(bible.close)
        with self.assertRaises(SearchValidationError):
            bible.search("   ", "kjv")
        with self.assertRaises(RequestLimitError):
            bible.search("faith", "kjv", {"offset": 10_001})


class TestRepositoryBoundaries(unittest.TestCase):
    def test_local_response_size_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resource = root / "v2" / "test" / "books.json"
            resource.parent.mkdir(parents=True)
            resource.write_bytes(b"{}")
            client = RepositoryClient(root, max_response_bytes=1)
            with self.assertRaises(RepositoryResponseTooLarge):
                client.fetch_bytes("test/books.json")

    def test_repository_paths_cannot_escape_the_root(self) -> None:
        client = RepositoryClient("/tmp/repository")
        for path in ("../secret", "/etc/passwd", "test/../../secret"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    client.location(path)

    def test_timeout_and_retry_arguments_are_bounded(self) -> None:
        with self.assertRaises(ValueError):
            RepositoryClient("/tmp/repository", retries=11)
        with self.assertRaises(ValueError):
            RepositoryClient("/tmp/repository", timeout=(0, 1))


if __name__ == "__main__":
    unittest.main()
