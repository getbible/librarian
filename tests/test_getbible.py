import unittest
import json
from getbible import GetBible


class TestGetBible(unittest.TestCase):

    def setUp(self):
        self.getbible = GetBible()

    def test_valid_reference(self):
        actual_result = json.loads(self.getbible.scripture('Gen 1:2-7', 'kjv'))
        expected_result = {
            "kjv_1_1": {"translation": "King James Version", "abbreviation": "kjv", "lang": "en", "language": "English",
                        "direction": "LTR", "encoding": "UTF-8", "book_nr": 1, "book_name": "Genesis", "chapter": 1,
                        "name": "Genesis 1", "ref": ["Gen 1:2-7"], "verses": [{"chapter": 1, "verse": 2, "name": "Genesis 1:2",
                                                         "text": "And the earth was without form and void; and darkness was upon the face of the deep. And the Spirit of God moved upon the face of the waters."},
                                                        {"chapter": 1, "verse": 3, "name": "Genesis 1:3",
                                                         "text": "And God said, Let there be light: and there was light."},
                                                        {"chapter": 1, "verse": 4, "name": "Genesis 1:4",
                                                         "text": "And God saw the light, that it was good: and God divided the light from the darkness."},
                                                        {"chapter": 1, "verse": 5, "name": "Genesis 1:5",
                                                         "text": "And God called the light Day, and the darkness he called Night. And the evening and the morning were the first day."},
                                                        {"chapter": 1, "verse": 6, "name": "Genesis 1:6",
                                                         "text": "And God said, Let there be a firmament in the midst of the waters, and let it divide the waters from the waters."},
                                                        {"chapter": 1, "verse": 7, "name": "Genesis 1:7",
                                                         "text": "And God made the firmament, and divided the waters which were under the firmament from the waters which were above the firmament: and it was so."}]}}
        self.assertEqual(actual_result, expected_result, "Failed to find 'Gen 1:2-7' scripture.")

    def test_valid_reference_cns(self):
        actual_result = json.loads(self.getbible.scripture('创世记1:2-7', 'cns'))
        expected_result = {
            "cns_1_1": {"translation": "NCV Simplified", "abbreviation": "cns", "lang": "zh-Hans",
                        "language": "Chinese",
                        "direction": "LTR", "encoding": "UTF-8", "book_nr": 1, "book_name": "\ufeff\u521b\u4e16\u8bb0",
                        "chapter": 1, "name": "\ufeff\u521b\u4e16\u8bb0 1", "ref": ["创世记1:2-7"], "verses": [
                    {"chapter": 1, "verse": 2, "name": "\ufeff\u521b\u4e16\u8bb0 1:2",
                     "text": "\u5730\u662f\u7a7a\u865a\u6df7\u6c8c\uff1b\u6df1\u6e0a\u4e0a\u4e00\u7247\u9ed1\u6697\uff1b\u3000\u795e\u7684\u7075\u8fd0\u884c\u5728\u6c34\u9762\u4e0a\u3002 "},
                    {"chapter": 1, "verse": 3, "name": "\ufeff\u521b\u4e16\u8bb0 1:3",
                     "text": "\u795e\u8bf4\uff1a\u201c\u8981\u6709\u5149\uff01\u201d\u5c31\u6709\u4e86\u5149\u3002 "},
                    {"chapter": 1, "verse": 4, "name": "\ufeff\u521b\u4e16\u8bb0 1:4",
                     "text": "\u795e\u770b\u5149\u662f\u597d\u7684\uff0c\u4ed6\u5c31\u628a\u5149\u6697\u5206\u5f00\u4e86\u3002 "},
                    {"chapter": 1, "verse": 5, "name": "\ufeff\u521b\u4e16\u8bb0 1:5",
                     "text": "\u795e\u79f0\u5149\u4e3a\u663c\uff0c\u79f0\u6697\u4e3a\u591c\u3002\u6709\u665a\u4e0a\uff0c\u6709\u65e9\u6668\uff1b\u8fd9\u662f\u7b2c\u4e00\u65e5\u3002 "},
                    {"chapter": 1, "verse": 6, "name": "\ufeff\u521b\u4e16\u8bb0 1:6",
                     "text": "\u795e\u8bf4\uff1a\u201c\u4f17\u6c34\u4e4b\u95f4\u8981\u6709\u7a79\u82cd\uff0c\u628a\u6c34\u548c\u6c34\u5206\u5f00\uff01\u201d\u4e8b\u5c31\u8fd9\u6837\u6210\u4e86\u3002 "},
                    {"chapter": 1, "verse": 7, "name": "\ufeff\u521b\u4e16\u8bb0 1:7",
                     "text": "\u795e\u9020\u4e86\u7a79\u82cd\uff0c\u628a\u7a79\u82cd\u4ee5\u4e0b\u7684\u6c34\u548c\u7a79\u82cd\u4ee5\u4e0a\u7684\u6c34\u5206\u5f00\u4e86\u3002 "}]}}
        self.assertEqual(actual_result, expected_result, "Failed to find '创世记1:2-7' scripture.")

    def test_valid_multiple_reference_aov(self):
        actual_result = json.loads(self.getbible.scripture('Ge1:1;Jn1:1;1Jn1:1', 'aov'))
        expected_result = {
            "aov_1_1": {"translation": "Ou Vertaling", "abbreviation": "aov", "lang": "af", "language": "Afrikaans",
                        "direction": "LTR", "encoding": "UTF-8", "book_nr": 1, "book_name": "Genesis", "chapter": 1,
                        "name": "Genesis 1", "ref": ['Ge1:1'], "verses": [{"chapter": 1, "verse": 1, "name": "Genesis 1:1",
                                                         "text": "In die begin het God die hemel en die aarde geskape. "}]},
            "aov_43_1": {"translation": "Ou Vertaling", "abbreviation": "aov", "lang": "af", "language": "Afrikaans",
                         "direction": "LTR", "encoding": "UTF-8", "book_nr": 43, "book_name": "Johannes", "chapter": 1,
                         "name": "Johannes 1", "ref": ['Jn1:1'], "verses": [{"chapter": 1, "verse": 1, "name": "Johannes 1:1",
                                                           "text": "In die begin was die Woord, en die Woord was by God, en die Woord was God. "}]},
            "aov_62_1": {"translation": "Ou Vertaling", "abbreviation": "aov", "lang": "af", "language": "Afrikaans",
                         "direction": "LTR", "encoding": "UTF-8", "book_nr": 62, "book_name": "1 Johannes",
                         "chapter": 1, "name": "1 Johannes 1", "ref": ["1Jn1:1"], "verses": [
                    {"chapter": 1, "verse": 1, "name": "1 Johannes 1:1",
                     "text": "Wat van die begin af was, wat ons gehoor het, wat ons met ons o\u00eb gesien het, wat ons aanskou het en ons hande getas het aangaande die Woord van die lewe \u2014 "}]}}
        self.assertEqual(actual_result, expected_result, "Failed to find 'Ge1:1;Jn1:1;1Jn1:1' scripture.")

    def test_valid_multiple_reference_select_aleppo(self):
        actual_result = self.getbible.select('Ge1:1-3;Ps1:1;ps1:1-2;Ge1:6-7,10', 'aleppo')
        expected_result = {
            'aleppo_19_1': {'abbreviation': 'aleppo',
                            'book_name': 'תְּהִלִּים',
                            'book_nr': 19,
                            'chapter': 1,
                            'direction': 'RTL',
                            'encoding': 'UTF-8',
                            'lang': 'hbo',
                            'language': 'Hebrew',
                            'name': 'תְּהִלִּים 1',
                            'translation': 'Aleppo Codex',
                            'ref': ['Ps1:1', 'ps1:1-2'],
                            'verses': [{'chapter': 1,
                                        'name': 'תְּהִלִּים 1:1',
                                        'text': '\xa0\xa0אשרי האיש— \xa0\xa0 אשר לא הלך '
                                                'בעצת רשעיםובדרך חטאים לא עמד \xa0\xa0 '
                                                'ובמושב לצים לא ישב ',
                                        'verse': 1},
                                       {'chapter': 1,
                                        'name': 'תְּהִלִּים 1:2',
                                        'text': '\xa0\xa0כי אם בתורת יהוה חפצו \xa0\xa0 '
                                                'ובתורתו יהגה יומם ולילה ',
                                        'verse': 2}]},
            'aleppo_1_1': {'abbreviation': 'aleppo',
                           'book_name': 'בְּרֵאשִׁית',
                           'book_nr': 1,
                           'chapter': 1,
                           'direction': 'RTL',
                           'encoding': 'UTF-8',
                           'lang': 'hbo',
                           'language': 'Hebrew',
                           'name': 'בְּרֵאשִׁית 1',
                           'translation': 'Aleppo Codex',
                           'ref': ['Ge1:1-3', 'Ge1:6-7,10'],
                           'verses': [{'chapter': 1,
                                       'name': 'בְּרֵאשִׁית 1:1',
                                       'text': 'בראשית ברא אלהים את השמים ואת הארץ ',
                                       'verse': 1},
                                      {'chapter': 1,
                                       'name': 'בְּרֵאשִׁית 1:2',
                                       'text': 'והארץ היתה תהו ובהו וחשך על פני תהום ורוח '
                                               'אלהים מרחפת על פני המים ',
                                       'verse': 2},
                                      {'chapter': 1,
                                       'name': 'בְּרֵאשִׁית 1:3',
                                       'text': 'ויאמר אלהים יהי אור ויהי אור ',
                                       'verse': 3},
                                      {'chapter': 1,
                                       'name': 'בְּרֵאשִׁית 1:6',
                                       'text': 'ויאמר אלהים יהי רקיע בתוך המים ויהי מבדיל '
                                               'בין מים למים ',
                                       'verse': 6},
                                      {'chapter': 1,
                                       'name': 'בְּרֵאשִׁית 1:7',
                                       'text': 'ויעש אלהים את הרקיע ויבדל בין המים אשר '
                                               'מתחת לרקיע ובין המים אשר מעל לרקיע ויהי '
                                               'כן ',
                                       'verse': 7},
                                      {'chapter': 1,
                                       'name': 'בְּרֵאשִׁית 1:10',
                                       'text': 'ויקרא אלהים ליבשה ארץ ולמקוה המים קרא '
                                               'ימים וירא אלהים כי טוב ',
                                       'verse': 10}]
                           }
        }

        self.assertEqual(actual_result, expected_result, "Failed to find 'Ge1:1-3;Ps1:1;ps1:1-2;Ge1:6-7,1' scripture.")

    def test_invalid_reference_select_aleppo(self):
        expected_exception = "Chapter:111 in book:1 for aleppo not found."
        with self.assertRaises(FileNotFoundError) as actual:
            self.getbible.select('Ge111', 'aleppo')
        self.assertEqual(str(actual.exception), expected_exception)

    def test_invalid_reference_select_kjv(self):
        expected_exception = "Verse 111 not found in book 1, chapter 1."
        with self.assertRaises(ValueError) as actual:
            self.getbible.select('Ge 1:111', 'kjv')
        self.assertEqual(str(actual.exception), expected_exception)

    def test_invalid_double_dash_reference_select_kjv(self):
        expected_exception = "Invalid reference 'Ge 1:1-7-11'."
        with self.assertRaises(ValueError) as actual:
            self.getbible.select('Ge 1:1-7-11', 'kjv')
        self.assertEqual(str(actual.exception), expected_exception)

    def test_invalid_verse_reference_select_kjv(self):
        expected_exception = "Verse 32 not found in book 1, chapter 1."
        with self.assertRaises(ValueError) as actual:
            self.getbible.select('1 1:1-80', 'kjv')
        self.assertEqual(str(actual.exception), expected_exception)

    def test_invalid_book_reference_select_kjv(self):
        expected_exception = "Invalid reference '112 1:1-80'."
        with self.assertRaises(ValueError) as actual:
            self.getbible.select('112 1:1-80', 'kjv')
        self.assertEqual(str(actual.exception), expected_exception)

if __name__ == '__main__':
    unittest.main()
