import json
import time
import unittest

import requests

from getbible import (
    DataValidationError,
    GetBible,
    GetBibleReference,
    InvalidReferenceError,
    UpstreamUnavailableError,
)


class FakeBookNumbers:
    translations = frozenset({"kjv", "aov"})

    def __init__(self):
        self.calls = []

    def number(self, reference, translation_code=None, fallback_translations=None):
        self.calls.append((reference, translation_code))
        values = {
            "gen": 1,
            "genesis": 1,
            "john": 43,
            "1 john": 62,
            "1jn": 62,
            "创世记": 1,
            "בְּרֵאשִׁית": 1,
        }
        if str(reference).isdigit():
            number = int(reference)
            return number if 1 <= number <= 83 else None
        return values.get(str(reference).casefold())


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, path, timeout):
        self.calls.append((path, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        return None


class ReferenceHardeningTests(unittest.TestCase):
    def setUp(self):
        self.books = FakeBookNumbers()
        self.parser = GetBibleReference(
            max_verses=100,
            book_number_resolver=self.books,
        )

    def test_valid_multilingual_and_compact_references(self):
        self.assertEqual(self.parser.ref("John 3:16", "kjv").verses, [16])
        self.assertEqual(self.parser.ref("1Jn1:1", "kjv").book, 62)
        self.assertEqual(self.parser.ref("创世记1:2-4", "kjv").verses, [2, 3, 4])
        self.assertEqual(self.parser.ref("בְּרֵאשִׁית 1:1", "kjv").book, 1)

    def test_huge_range_is_rejected_before_allocation(self):
        started = time.monotonic()
        with self.assertRaises(InvalidReferenceError):
            self.parser.ref("John 1:1-999999999", "kjv")
        self.assertLess(time.monotonic() - started, 0.1)

    def test_work_budget_rejects_large_but_syntactic_range(self):
        with self.assertRaisesRegex(InvalidReferenceError, "at most 100"):
            self.parser.ref("John 1:1-101", "kjv")

    def test_partial_match_and_dangling_ranges_are_rejected(self):
        for value in ("John 1:16!", "John 1:2-", "John 1:-5", "John 1:1-3junk"):
            with self.subTest(value=value), self.assertRaises(InvalidReferenceError):
                self.parser.ref(value, "kjv")

    def test_reversed_range_is_rejected(self):
        with self.assertRaisesRegex(InvalidReferenceError, "ascending"):
            self.parser.ref("John 1:10-2", "kjv")

    def test_invalid_input_never_falls_back_to_verse_one(self):
        with self.assertRaises(InvalidReferenceError):
            self.parser.ref("John 1:garbage", "kjv")

    def test_cache_key_includes_translation(self):
        self.parser.ref("John 1:1", "kjv")
        self.parser.ref("John 1:1", "aov")
        self.assertEqual(self.books.calls, [("John", "kjv"), ("John", "aov")])


class ClientHardeningTests(unittest.TestCase):
    @staticmethod
    def parser(max_verses=100):
        return GetBibleReference(
            max_verses=max_verses,
            book_number_resolver=FakeBookNumbers(),
        )

    def test_unknown_translation_performs_no_request(self):
        session = FakeSession([])
        client = GetBible(session=session, reference_parser=self.parser())
        self.assertFalse(client.valid_translation("3:16"))
        self.assertFalse(client.valid_translation("not_known"))
        self.assertEqual(session.calls, [])

    def test_timeout_is_explicit_and_mapped(self):
        session = FakeSession([requests.Timeout("late")])
        client = GetBible(
            session=session,
            reference_parser=self.parser(),
            connect_timeout=1.5,
            read_timeout=4.5,
        )
        with self.assertRaises(UpstreamUnavailableError):
            client.valid_translation("kjv")
        self.assertEqual(session.calls[0][1], (1.5, 4.5))

    def test_invalid_json_is_not_treated_as_missing_translation(self):
        session = FakeSession([FakeResponse(payload=ValueError("bad json"))])
        client = GetBible(session=session, reference_parser=self.parser())
        with self.assertRaises(DataValidationError):
            client.valid_translation("kjv")

    def test_reference_and_total_verse_limits_are_enforced(self):
        session = FakeSession([FakeResponse(payload={})])
        client = GetBible(
            session=session,
            reference_parser=self.parser(max_verses=10),
            max_references=2,
            max_total_verses=10,
        )
        with self.assertRaisesRegex(InvalidReferenceError, "at most 2 references"):
            client.select("John 1:1;John 1:2;John 1:3", "kjv")
        with self.assertRaisesRegex(InvalidReferenceError, "at most 10 verses"):
            client.select("John 1:1-6;John 1:7-12", "kjv")

    def test_local_repository_happy_path(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "v2" / "kjv"
            (root / "43").mkdir(parents=True)
            (root / "books.json").write_text("{}", encoding="utf-8")
            chapter = {
                "translation": "King James Version",
                "abbreviation": "kjv",
                "book_name": "John",
                "chapter": 3,
                "verses": [
                    {"chapter": 3, "verse": 16, "text": "For God so loved the world."}
                ],
            }
            (root / "43" / "3.json").write_text(json.dumps(chapter), encoding="utf-8")
            client = GetBible(
                repo_path=directory,
                reference_parser=self.parser(),
                max_total_verses=10,
            )
            result = client.select("John 3:16", "kjv")
            self.assertEqual(result["kjv_43_3"]["verses"][0]["verse"], 16)


if __name__ == "__main__":
    unittest.main()
