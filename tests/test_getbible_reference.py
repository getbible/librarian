import unittest
from getbible import GetBibleReference
from getbible import BookReference


class TestGetBibleReference(unittest.TestCase):
    def setUp(self):
        self.get = GetBibleReference()

    def test_valid_reference(self):
        expected_result = BookReference(book=1, chapter=1, verses=[2, 3, 4, 5, 6, 7])
        actual_result = self.get.ref('Gen 1:2-7', 'kjv')
        self.assertEqual(actual_result, expected_result, "Failed to find 'Gen 1:2-7' book reference.")

    def test_valid_reference_ch(self):
        expected_result = BookReference(book=1, chapter=1, verses=[2, 3, 4, 5, 6, 7])
        actual_result = self.get.ref('创世记1:2-7', 'cns')
        self.assertEqual(actual_result, expected_result, "Failed to find '创世记1:2-7' book reference")

    def test_valid_reference_missing_verse_ch(self):
        expected_result = BookReference(book=1, chapter=1, verses=[2])
        actual_result = self.get.ref('创记 1:2-', 'cus')
        self.assertEqual(actual_result, expected_result, "Failed to find '创记 1:2-' book reference")

    def test_valid_reference_missing_verse__ch(self):
        expected_result = BookReference(book=1, chapter=1, verses=[5])
        actual_result = self.get.ref('创记 1:-5', 'cus')
        self.assertEqual(actual_result, expected_result, "Failed to find '创记 1:-5' book reference")

    def test_valid_reference_ch_no_trans(self):
        actual_result = self.get.ref('创世记')
        expected_result = BookReference(book=1, chapter=1, verses=[1])
        self.assertEqual(actual_result, expected_result, "Failed to find '创世记 1:1' book reference")

    def test_valid_reference_ch_no__trans(self):
        expected_result = BookReference(book=1, chapter=1, verses=[1])
        actual_result = self.get.ref('创记')
        self.assertEqual(actual_result, expected_result, "Failed to find '创记 1:1' book reference")

    def test_valid_1_john(self):
        expected_result = BookReference(book=62, chapter=1, verses=[1])
        actual_result = self.get.ref('1 John', 'kjv')
        self.assertEqual(actual_result, expected_result, "Failed to find '1 John 1:1' book reference")

    def test_valid_1_peter_ch(self):
        actual_result = self.get.ref('彼得前书', 'cns')
        expected_result = BookReference(book=60, chapter=1, verses=[1])
        self.assertEqual(actual_result, expected_result, "Failed to find '彼得前书 1:1' book reference")

    def test_valid_first_john(self):
        expected_result = BookReference(book=62, chapter=3, verses=[16, 19, 20, 21])
        actual_result = self.get.ref('First John 3:16,19-21', 'kjv')
        self.assertEqual(actual_result, expected_result, "Failed to find 'First John 1:2-7' book reference.")

    def test_valid_mismatch_nospace_call(self):
        expected_result = BookReference(book=62, chapter=1, verses=[1])
        actual_result = self.get.ref('1Jn', 'aov')
        self.assertEqual(actual_result, expected_result, "Failed to find '1Jn 1:1' book reference.")

    def test_valid_mismatch_call(self):
        expected_result = BookReference(book=62, chapter=5, verses=[1])
        actual_result = self.get.ref('1  John 5', 'aov')
        self.assertEqual(actual_result, expected_result, "Failed to find '1  John 5:1' book reference.")

    def test_invalid_reference(self):
        expected_exception = "Invalid reference 'NonExistent'."
        with self.assertRaises(ValueError) as actual:
            self.get.ref('NonExistent', 'kjv')
        self.assertEqual(str(actual.exception), expected_exception)

    def test_nonexistent_translation(self):
        expected_result = BookReference(book=1, chapter=1, verses=[1])
        actual_result = self.get.ref('Gen', 'nonexistent')
        self.assertEqual(actual_result, expected_result, "Failed to find 'Gen 1:1' book reference.")


if __name__ == '__main__':
    unittest.main()
