import time
import unittest

from getbible import BookReference, GetBibleReference, InvalidReferenceError


class TestGetBibleReference(unittest.TestCase):
    def setUp(self):
        self.parser = GetBibleReference(max_verses=100)

    def test_valid_multilingual_references(self):
        cases = (
            ("Gen 1:2-7", "kjv", BookReference(1, 1, [2, 3, 4, 5, 6, 7], "Gen 1:2-7")),
            ("创世记1:2-7", "cns", BookReference(1, 1, [2, 3, 4, 5, 6, 7], "创世记1:2-7")),
            ("رؤ 22:19", None, BookReference(66, 22, [19], "رؤ 22:19")),
            ("1Jn", "aov", BookReference(62, 1, [1], "1Jn")),
        )
        for reference, translation, expected in cases:
            with self.subTest(reference=reference):
                self.assertEqual(self.parser.ref(reference, translation), expected)

    def test_invalid_reference(self):
        with self.assertRaises(InvalidReferenceError):
            self.parser.ref("NonExistent", "kjv")

    def test_dangling_and_reversed_ranges_are_invalid(self):
        for reference in ("John 1:2-", "John 1:-5", "John 1:10-2"):
            with self.subTest(reference=reference), self.assertRaises(InvalidReferenceError):
                self.parser.ref(reference, "kjv")

    def test_partial_match_is_never_accepted(self):
        with self.assertRaises(InvalidReferenceError):
            self.parser.ref("John 1:16!", "kjv")

    def test_huge_range_fails_quickly(self):
        started = time.monotonic()
        with self.assertRaises(InvalidReferenceError):
            self.parser.ref("John 1:1-999999999", "kjv")
        self.assertLess(time.monotonic() - started, 0.1)


if __name__ == "__main__":
    unittest.main()
