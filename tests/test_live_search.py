import os
import unittest

from getbible import GetBible, SearchBible


@unittest.skipUnless(
    os.environ.get("GETBIBLE_RUN_LIVE_TESTS") == "1",
    "Set GETBIBLE_RUN_LIVE_TESTS=1 to run live API integration tests.",
)
class TestLiveSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bible = GetBible()

    def test_kjv_phrase_search_uses_verified_translation(self):
        response = self.bible.search(
            "in the beginning",
            "kjv",
            SearchBible(words="phrase", limit=5),
        )
        self.assertGreater(response["query"]["total"], 0)
        self.assertEqual(len(response["query"]["sha"]), 40)
        self.assertIn("results", response)
        self.assertIn("matches", response)

    def test_kjv_new_testament_scope(self):
        response = self.bible.search(
            "Jesus Christ",
            "kjv",
            SearchBible(words="phrase", scope="new_testament", limit=10),
        )
        self.assertGreater(response["query"]["total"], 0)
        self.assertTrue(
            all(match["book_nr"] >= 40 for match in response["matches"])
        )

    def test_chinese_continuous_script_search(self):
        response = self.bible.search("神爱世人", "cus")

        self.assertGreater(response["query"]["total"], 0)
        self.assertEqual(response["query"]["analysis"], {"script": "continuous"})
        self.assertTrue(
            any(
                match["book_nr"] == 43
                and match["chapter"] == 3
                and match["verse"] == 16
                for match in response["matches"]
            )
        )

    def test_hebrew_abjad_search(self):
        response = self.bible.search("בראשית", "aleppo")

        self.assertGreater(response["query"]["total"], 0)
        self.assertEqual(response["query"]["analysis"], {"script": "abjad"})
        self.assertTrue(
            any(
                match["book_nr"] == 1
                and match["chapter"] == 1
                and match["verse"] == 1
                for match in response["matches"]
            )
        )

    def test_arabic_abjad_search(self):
        response = self.bible.search("الرب", "arabicsv")

        self.assertGreater(response["query"]["total"], 0)
        self.assertEqual(response["query"]["analysis"], {"script": "abjad"})


if __name__ == "__main__":
    unittest.main()
