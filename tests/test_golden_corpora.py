"""Golden expectations against complete API translations.

These tests run against a real GetBible API v2 tree. They are skipped when one
is not present, so the default suite stays offline and deterministic, and they
become the release gate once a tree is available.

Expectations are not hard-coded verse lists. Each is derived from the payload
itself by a plain text scan, which reaches the answer by a different route than
the postings index does. The engine is then required to agree with that scan.
The property under test is the one that was reported broken: a search must not
miss verses that plainly contain what the reader asked for.

Point the suite at a tree with either layout::

    tests/fixtures/api/v2/<abbreviation>.json
    GETBIBLE_API_FIXTURES=/path/to/repository python -m unittest tests.test_golden_corpora
"""

import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import regex

from getbible import GetBible, SearchBible
from getbible.search import Analyzer, ScriptFamily, classify_text, normalize_text

_DEFAULT_TREE = Path(__file__).parent / "fixtures" / "api"
_PROBES_PER_TRANSLATION = 12
_WORD_BOUNDARY = r"[^\p{L}\p{N}\p{M}]"


def _repository_root() -> Path | None:
    configured = os.environ.get("GETBIBLE_API_FIXTURES")
    root = Path(configured) if configured else _DEFAULT_TREE
    return root if (root / "v2").is_dir() else None


def _translations(root: Path) -> list[tuple[str, Path]]:
    return sorted(
        (path.stem, path)
        for path in (root / "v2").glob("*.json")
        if path.stem != "translations"
    )


ROOT = _repository_root()


@unittest.skipIf(ROOT is None, "no GetBible API tree available")
class TestGoldenCorpora(unittest.TestCase):
    """Every translation present is validated against a plain text scan."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.bible = GetBible(repo_path=ROOT, cache_dir=cls.temporary.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.bible.close()
        cls.temporary.cleanup()

    @staticmethod
    def _verse_texts(payload: Path) -> list[str]:
        data = json.loads(payload.read_text(encoding="utf-8"))
        return [
            verse["text"]
            for book in data["books"]
            for chapter in book["chapters"]
            for verse in chapter["verses"]
        ]

    @staticmethod
    def _probes(texts: list[str], family: ScriptFamily) -> list[str]:
        """Draw probe queries from the translation's own frequent units.

        Deriving probes from the corpus keeps the test meaningful for any
        translation, including one added to the API after this was written.
        """
        analyzer = Analyzer()
        counts: Counter[str] = Counter()
        for text in texts[:4000]:
            for unit_family, unit in analyzer.runs(text):
                if unit_family is not family or len(unit) < 2:
                    continue
                counts[unit] += 1
        return [unit for unit, _ in counts.most_common(_PROBES_PER_TRANSLATION)]

    @staticmethod
    def _scan(texts: list[str], probe: str, family: ScriptFamily) -> set[int]:
        """Ground truth: which verses plainly contain the probe."""
        folded = Analyzer().prepare(probe)
        if family is ScriptFamily.CONTINUOUS:
            return {
                ordinal
                for ordinal, text in enumerate(texts)
                if folded in Analyzer().prepare(text)
            }
        pattern = regex.compile(
            rf"(?<!{_WORD_BOUNDARY.replace('^', '')}){regex.escape(folded)}"
            rf"(?={_WORD_BOUNDARY}|\Z)"
        )
        return {
            ordinal
            for ordinal, text in enumerate(texts)
            if pattern.search(Analyzer().prepare(text))
        }

    def _matched_ordinals(self, abbreviation: str, probe: str, total: int) -> set[int]:
        response = self.bible.search(
            probe, abbreviation, SearchBible(limit=1000, sort="canonical")
        )
        self.assertLessEqual(
            response["query"]["total"],
            total,
            "search reported more verses than the translation contains",
        )
        return {
            (int(match["book_nr"]), int(match["chapter"]), int(match["verse"]))
            for match in response["matches"]
        }

    def test_no_verse_that_plainly_contains_the_query_is_missed(self) -> None:
        root = ROOT
        assert root is not None
        for abbreviation, payload in _translations(root):
            texts = self._verse_texts(payload)
            family = classify_text(" ".join(texts[:400]))
            probes = self._probes(texts, family)
            self.assertTrue(probes, f"{abbreviation}: no probes could be drawn")
            for probe in probes:
                expected = self._scan(texts, probe, family)
                if not expected or len(expected) > 900:
                    continue
                with self.subTest(translation=abbreviation, probe=probe):
                    response = self.bible.search(
                        probe, abbreviation, SearchBible(limit=1000)
                    )
                    self.assertGreaterEqual(
                        response["query"]["total"],
                        len(expected),
                        f"{abbreviation}: '{probe}' occurs in {len(expected)} verses "
                        f"but search reported {response['query']['total']}",
                    )

    def test_continuous_scripts_agree_exactly_with_a_text_scan(self) -> None:
        root = ROOT
        assert root is not None
        for abbreviation, payload in _translations(root):
            texts = self._verse_texts(payload)
            family = classify_text(" ".join(texts[:400]))
            if family is not ScriptFamily.CONTINUOUS:
                continue
            for probe in self._probes(texts, family):
                expected = self._scan(texts, probe, family)
                if not expected or len(expected) > 900:
                    continue
                with self.subTest(translation=abbreviation, probe=probe):
                    response = self.bible.search(
                        probe, abbreviation, SearchBible(limit=1000)
                    )
                    self.assertEqual(response["query"]["total"], len(expected))

    def test_the_default_criteria_never_return_nothing_for_a_present_word(
        self,
    ) -> None:
        """The reported failure, stated directly and checked per translation."""
        root = ROOT
        assert root is not None
        for abbreviation, payload in _translations(root):
            texts = self._verse_texts(payload)
            family = classify_text(" ".join(texts[:400]))
            for probe in self._probes(texts, family)[:6]:
                with self.subTest(translation=abbreviation, probe=probe):
                    response = self.bible.search(probe, abbreviation)
                    self.assertGreater(
                        response["query"]["total"],
                        0,
                        f"{abbreviation}: default search found nothing for '{probe}'",
                    )

    def test_every_translation_reports_the_script_it_was_read_as(self) -> None:
        root = ROOT
        assert root is not None
        for abbreviation, payload in _translations(root):
            texts = self._verse_texts(payload)
            probe = self._probes(texts, classify_text(" ".join(texts[:400])))[0]
            with self.subTest(translation=abbreviation):
                response = self.bible.search(probe, abbreviation)
                self.assertIn(
                    response["query"]["analysis"]["script"],
                    {family.value for family in ScriptFamily},
                )

    def test_normalization_is_stable_across_the_whole_corpus(self) -> None:
        root = ROOT
        assert root is not None
        for abbreviation, payload in _translations(root):
            with self.subTest(translation=abbreviation):
                for text in self._verse_texts(payload)[:2000]:
                    self.assertEqual(
                        normalize_text(normalize_text(text)), normalize_text(text)
                    )


if __name__ == "__main__":
    unittest.main()
