import unittest
from getbible import GetBibleBookNumber


class TestGetBibleBookNumber(unittest.TestCase):

    def setUp(self):
        self.get_book = GetBibleBookNumber()

    def test_valid_reference(self):
        expected_result = 1
        actual_result = self.get_book.number('Gen', 'kjv')
        self.assertEqual(actual_result, expected_result, "Failed to find 'Gen' in 'kjv' translation")

    def test_valid_reference_ch(self):
        expected_result = 1
        actual_result = self.get_book.number('创世记', 'cns', ['cnt'])
        self.assertEqual(actual_result, expected_result, "Failed to find '创世记' in 'cns' translation with 'cnt' fallback")

    def test_valid_reference__ch(self):
        expected_result = 1
        actual_result = self.get_book.number('创记', 'cus', ['cut'])
        self.assertEqual(actual_result, expected_result, "Failed to find '创记' in 'cus' translation with 'cut' fallback")

    def test_valid_reference_ch_no_trans(self):
        expected_result = 1
        actual_result = self.get_book.number('创世记')
        self.assertEqual(actual_result, expected_result, "Failed to find '创世记' in 'none-given' translation")

    def test_valid_reference__ch_no_trans(self):
        expected_result = 1
        actual_result = self.get_book.number('创记')
        self.assertEqual(actual_result, expected_result, "Failed to find '创记' in 'none-given' translation")

    def test_valid_1_john(self):
        expected_result = 62
        actual_result = self.get_book.number('1 John', 'kjv')
        self.assertEqual(actual_result, expected_result, "Failed to find '1 John' in 'kjv' translation")

    def test_valid_genesis(self):
        expected_result = 1
        actual_result = self.get_book.number('בְּרֵאשִׁית', 'codex')
        self.assertEqual(actual_result, expected_result, "Failed to find 'בְּרֵאשִׁית' in 'codex' translation")

    def test_valid_1_samuel(self):
        expected_result = 9
        actual_result = self.get_book.number("שמא",'aleppo')
        self.assertEqual(actual_result, expected_result, "Failed to find 'שמא' in 'aleppo' translation")

    def test_valid_1_peter_ch(self):
        expected_result = 60
        actual_result = self.get_book.number('彼得前书', 'cns')
        self.assertEqual(actual_result, expected_result, "Failed to find '彼得前书' in 'cns' translation")

    def test_valid_first_john(self):
        expected_result = 62
        actual_result = self.get_book.number('First John', 'kjv')
        self.assertEqual(actual_result, expected_result, "Failed to find 'First John' in 'kjv' translation")

    def test_valid_one_john(self):
        expected_result = 62
        actual_result = self.get_book.number('62', 'kjv')
        self.assertEqual(actual_result, expected_result, "Failed to find '62' in 'kjv' translation")

    def test_wrong_book_number(self):
        actual_result = self.get_book.number('84', 'kjv')
        self.assertIsNone(actual_result, "Failed to limit the books in 'kjv' translation to 1-83")

    def test_wrong_book_number_zero(self):
        actual_result = self.get_book.number('0', 'kjv')
        self.assertIsNone(actual_result, "Failed to limit the books in 'kjv' translation to 1-83")

    def test_wrong_book_number_minus(self):
        actual_result = self.get_book.number('-19', 'kjv')
        self.assertIsNone(actual_result, "Failed to limit the books in 'kjv' translation to 1-83")

    def test_valid_mismatch_nospace_call(self):
        expected_result = 62
        actual_result = self.get_book.number('1Jn', 'aov')
        self.assertEqual(actual_result, expected_result, "Failed to find '1Jn' in 'aov' translation with 'kjv' as fallback translation")

    def test_valid_mismatch_call(self):
        expected_result = 62
        actual_result = self.get_book.number('1 John', 'aov')
        self.assertEqual(actual_result, expected_result, "Failed to find '1 John' in 'aov' translation with 'kjv' as fallback translation")

    def test_invalid_reference(self):
        actual_result = self.get_book.number('NonExistent', 'kjv')
        self.assertIsNone(actual_result, "Invalid reference 'NonExistent' unexpectedly found in 'kjv'")

    def test_nonexistent_translation(self):
        expected_result = 1
        actual_result = self.get_book.number('Gen', 'nonexistent', ['nonexistent', 'nonexistent'])
        self.assertEqual(actual_result, expected_result, "Fallback to 'kjv' did not work for non-existent translation")

    def test_fallback_translation(self):
        expected_result = 1
        actual_result = self.get_book.number('Gen', 'bad-translation')
        self.assertEqual(actual_result, expected_result, "Fallback to 'kjv' did not work for 'bad-translation'")


if __name__ == '__main__':
    unittest.main()
