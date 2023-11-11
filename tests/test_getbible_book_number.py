import unittest
from getbible import GetBibleBookNumber


class TestGetBibleBookNumber(unittest.TestCase):

    def setUp(self):
        self.get_book = GetBibleBookNumber()

    def test_valid_reference(self):
        self.assertEqual(self.get_book.number('Gen', 'kjv'), '1', "Failed to find 'Gen' in 'kjv' translation")

    def test_valid_reference_ch(self):
        self.assertEqual(self.get_book.number('创世记', 'cns', ['cnt']), '1',
                         "Failed to find '创世记' in 'cns' translation with 'cnt' fallback")
        self.assertEqual(self.get_book.number('创记', 'cus', ['cut']), '1',
                         "Failed to find '创记' in 'cus' translation with 'cut' fallback")

    def test_valid_reference_ch_no_trans(self):
        self.assertEqual(self.get_book.number('创世记'), '1', "Failed to find '创世记' in 'none-given' translation")
        self.assertEqual(self.get_book.number('创记'), '1', "Failed to find '创记' in 'none-given' translation")

    def test_valid_1_john(self):
        self.assertEqual(self.get_book.number('1 John', 'kjv'), '62', "Failed to find '1 John' in 'kjv' translation")

    def test_valid_1_peter_ch(self):
        self.assertEqual(self.get_book.number('彼得前书', 'cns'), '60',
                         "Failed to find '彼得前书' in 'cns' translation")

    def test_valid_first_john(self):
        self.assertEqual(self.get_book.number('First John', 'kjv'), '62',
                         "Failed to find 'First John' in 'kjv' translation")

    def test_valid_mismatch_nospace_call(self):
        self.assertEqual(self.get_book.number('1Jn', 'aov'), '62',
                         "Failed to find '1Jn' in 'aov' translation with 'kjv' as fallback translation")

    def test_valid_mismatch_call(self):
        self.assertEqual(self.get_book.number('1 John', 'aov'), '62',
                         "Failed to find '1 John' in 'aov' translation with 'kjv' as fallback translation")

    def test_invalid_reference(self):
        self.assertIsNone(self.get_book.number('NonExistent', 'kjv'),
                          "Invalid reference 'NonExistent' unexpectedly found in 'kjv'")

    def test_nonexistent_translation(self):
        self.assertEqual(self.get_book.number('Gen', 'nonexistent', ['nonexistent', 'nonexistent']), '1',
                         "Fallback to 'kjv' did not work for non-existent translation")

    def test_fallback_translation(self):
        self.assertEqual(self.get_book.number('Gen', 'bad-translation'), '1',
                         "Fallback to 'kjv' did not work for 'bad-translation'")


if __name__ == '__main__':
    unittest.main()
