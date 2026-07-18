import json
from pathlib import Path
import tempfile
import unittest

from getbible import GetBible, InvalidReferenceError, ScriptureNotFoundError


class TestGetBibleOffline(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "v2" / "kjv"
        (self.root / "43").mkdir(parents=True)
        (self.root / "books.json").write_text("{}", encoding="utf-8")
        chapter = {
            "translation": "King James Version",
            "abbreviation": "kjv",
            "lang": "en",
            "language": "English",
            "direction": "LTR",
            "encoding": "UTF-8",
            "book_nr": 43,
            "book_name": "John",
            "chapter": 3,
            "name": "John 3",
            "verses": [
                {
                    "chapter": 3,
                    "verse": 16,
                    "name": "John 3:16",
                    "text": "For God so loved the world.",
                }
            ],
        }
        (self.root / "43" / "3.json").write_text(json.dumps(chapter), encoding="utf-8")
        self.getbible = GetBible(
            repo_path=self.temporary_directory.name,
            max_references=2,
            max_total_verses=10,
        )

    def tearDown(self):
        self.getbible.close()
        self.temporary_directory.cleanup()

    def test_valid_reference(self):
        result = self.getbible.select("John 3:16", "kjv")
        self.assertEqual(result["kjv_43_3"]["verses"][0]["verse"], 16)
        self.assertEqual(result["kjv_43_3"]["ref"], ["John 3:16"])

    def test_scripture_json_is_unicode_safe(self):
        result = json.loads(self.getbible.scripture("John 3:16", "kjv"))
        self.assertEqual(result["kjv_43_3"]["book_name"], "John")

    def test_missing_verse_has_typed_error(self):
        with self.assertRaises(ScriptureNotFoundError):
            self.getbible.select("John 3:17", "kjv")

    def test_request_limits(self):
        with self.assertRaises(InvalidReferenceError):
            self.getbible.select("John 3:16;John 3:16;John 3:16", "kjv")


if __name__ == "__main__":
    unittest.main()
