import os
import unittest

from getbible import GetBible, SearchCriteria


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
            SearchCriteria(words="phrase", limit=5),
        )
        self.assertGreater(response["query"]["total"], 0)
        self.assertEqual(len(response["query"]["sha"]), 40)
        self.assertIn("results", response)
        self.assertIn("matches", response)

    def test_kjv_new_testament_scope(self):
        response = self.bible.search(
            "Jesus Christ",
            "kjv",
            SearchCriteria(words="phrase", scope="new_testament", limit=10),
        )
        self.assertGreater(response["query"]["total"], 0)
        self.assertTrue(
            all(match["book_nr"] >= 40 for match in response["matches"])
        )


if __name__ == "__main__":
    unittest.main()
