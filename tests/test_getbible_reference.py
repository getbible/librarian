import unittest
from getbible import GetBibleReference
from getbible import BookReference


class TestGetBibleReference(unittest.TestCase):
    def setUp(self):
        self.get = GetBibleReference()

    def test_valid_reference(self):
        self.assertEqual(self.get.ref('Gen 1:2-7', 'kjv'), BookReference(book=1, chapter=1, verses=[2, 3, 4, 5, 6, 7]),
                         "Failed to find 'Gen 1:2-7' book reference.")

    def test_valid_reference_ch(self):
        self.assertEqual(self.get.ref('创世记1:2-7', 'cns'),
                         BookReference(book=1, chapter=1, verses=[2, 3, 4, 5, 6, 7]),
                         "Failed to find '创世记1:2-7' book reference")
        self.assertEqual(self.get.ref('创记 1:2-', 'cus'), BookReference(book=1, chapter=1, verses=[2]),
                         "Failed to find '创记 1:2-' book reference")

    def test_valid_reference_ch_no_trans(self):
        self.assertEqual(self.get.ref('创世记'), BookReference(book=1, chapter=1, verses=[1]),
                         "Failed to find '创世记 1:1' book reference")
        self.assertEqual(self.get.ref('创记'), BookReference(book=1, chapter=1, verses=[1]),
                         "Failed to find '创记 1:1' book reference")

    def test_valid_1_john(self):
        self.assertEqual(self.get.ref('1 John', 'kjv'), BookReference(book=62, chapter=1, verses=[1]),
                         "Failed to find '1 John 1:1' book reference")

    def test_valid_1_peter_ch(self):
        self.assertEqual(self.get.ref('彼得前书', 'cns'), BookReference(book=60, chapter=1, verses=[1]),
                         "Failed to find '彼得前书 1:1' book reference")

    def test_valid_first_john(self):
        self.assertEqual(self.get.ref('First John 3:16,19-21', 'kjv'),
                         BookReference(book=62, chapter=3, verses=[16, 19, 20, 21]),
                         "Failed to find 'First John 1:2-7' book reference.")

    def test_valid_mismatch_nospace_call(self):
        self.assertEqual(self.get.ref('1Jn', 'aov'), BookReference(book=62, chapter=1, verses=[1]),
                         "Failed to find '1Jn 1:1' book reference.")

    def test_valid_mismatch_call(self):
        self.assertEqual(self.get.ref('1  John 5', 'aov'), BookReference(book=62, chapter=5, verses=[1]),
                         "Failed to find '1  John 5:1' book reference.")

    def test_invalid_reference(self):
        with self.assertRaises(ValueError) as context:
            self.get.ref('NonExistent', 'kjv')
        self.assertEqual(str(context.exception), "Book number for 'NonExistent' could not be found.")

    def test_nonexistent_translation(self):
        self.assertEqual(self.get.ref('Gen', 'nonexistent'), BookReference(book=1, chapter=1, verses=[1]),
                         "Failed to find 'Gen 1:1' book reference.")


if __name__ == '__main__':
    unittest.main()
