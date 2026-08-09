"""Script-aware text analysis shared by index construction and query parsing.

Librarian indexes many writing systems from one API contract. A single
tokenizer cannot serve them: Latin and Cyrillic separate words with spaces,
Han and Thai do not separate them at all, Hangul attaches grammatical endings
directly to the stem, and Hebrew and Arabic attach clitics and carry optional
vowel pointing.

This module turns text into :class:`Token` values using the writing system the
text is actually in, and it applies the same rules to a query as it applied to
the corpus. Because both sides pass through here, callers never choose a
matching strategy: the engine derives it. That is the whole of the language
business logic, kept inside the library.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

import regex

__all__ = [
    "Analyzer",
    "ScriptFamily",
    "Token",
    "analyzer_for",
    "casefold_text",
    "classify_text",
    "continuous_chain",
    "fold_marks",
    "normalize_text",
    "normalize_book_name",
    "script_census",
]


class ScriptFamily(str, Enum):
    """How a writing system delimits and inflects its searchable units."""

    #: Latin, Cyrillic, Greek, Armenian, Georgian, Coptic, Cherokee and peers.
    #: Spaces delimit words; combining marks are accents that readers omit.
    ALPHABETIC = "alphabetic"

    #: Han, kana, Hangul, Thai, Lao, Khmer, Myanmar, Tibetan and peers. Either
    #: nothing delimits the units, or the delimiter does not bound a searchable
    #: word. Indexed as overlapping character n-grams with positions.
    CONTINUOUS = "continuous"

    #: Hebrew, Arabic, Syriac, Thaana, Samaritan. Spaces delimit words, vowel
    #: pointing is optional, and closed-class particles attach to the word.
    ABJAD = "abjad"

    #: Devanagari, Bengali, Tamil, Sinhala and peers. Spaces delimit words, but
    #: combining marks carry vowels and must never be folded away.
    BRAHMIC = "brahmic"


_WORD_START: Final = r"\p{L}\p{N}"
_WORD_BODY: Final = rf"{_WORD_START}\p{{M}}‌‍"
_WORD: Final = regex.compile(
    rf"[{_WORD_START}][{_WORD_BODY}]*(?:['’][{_WORD_START}][{_WORD_BODY}]*)*"
)
_GRAPHEME: Final = regex.compile(r"\X")

# One character class per family. Membership is decided by Unicode property, so
# a translation in a script nobody anticipated still lands in a sane family
# instead of falling off the end of a hand-maintained range table.
_CONTINUOUS_CLASS: Final = (
    r"\p{Script_Extensions=Han}"
    r"\p{Script_Extensions=Hiragana}"
    r"\p{Script_Extensions=Katakana}"
    r"\p{Script_Extensions=Hangul}"
    r"\p{Script_Extensions=Tibetan}"
    r"\p{Line_Break=Complex_Context}"
)
_ABJAD_CLASS: Final = (
    r"\p{Script_Extensions=Hebrew}"
    r"\p{Script_Extensions=Arabic}"
    r"\p{Script_Extensions=Syriac}"
    r"\p{Script_Extensions=Thaana}"
    r"\p{Script_Extensions=Samaritan}"
)
_BRAHMIC_CLASS: Final = (
    r"\p{Script_Extensions=Devanagari}"
    r"\p{Script_Extensions=Bengali}"
    r"\p{Script_Extensions=Gurmukhi}"
    r"\p{Script_Extensions=Gujarati}"
    r"\p{Script_Extensions=Oriya}"
    r"\p{Script_Extensions=Tamil}"
    r"\p{Script_Extensions=Telugu}"
    r"\p{Script_Extensions=Kannada}"
    r"\p{Script_Extensions=Malayalam}"
    r"\p{Script_Extensions=Sinhala}"
)

_CONTINUOUS_CHAR: Final = regex.compile(rf"[{_CONTINUOUS_CLASS}]")
_ABJAD_CHAR: Final = regex.compile(rf"[{_ABJAD_CLASS}]")
_BRAHMIC_CHAR: Final = regex.compile(rf"[{_BRAHMIC_CLASS}]")
_LETTER: Final = regex.compile(r"[\p{L}\p{N}]")

# A run is a maximal stretch of one family. Splitting text into runs is what
# lets a Hebrew verse containing a Latin proper noun, or a mixed
# "Jesus—耶稣—イエス" verse, analyse every part by its own rules instead of
# forcing one strategy onto the whole string.
#
# Each class is intersected with letters and numbers so script-specific
# punctuation — the Hebrew sof pasuq, the Devanagari danda, the ideographic
# full stop — bounds a run instead of being absorbed into the word.
_RUN_PATTERNS: Final = (
    (
        ScriptFamily.CONTINUOUS,
        regex.compile(rf"(?V1)[[{_CONTINUOUS_CLASS}]&&[\p{{L}}\p{{N}}\p{{M}}]]+"),
    ),
    (
        ScriptFamily.ABJAD,
        regex.compile(rf"(?V1)[[{_ABJAD_CLASS}]&&[\p{{L}}\p{{N}}\p{{M}}]‌‍]+"),
    ),
    (
        ScriptFamily.BRAHMIC,
        regex.compile(rf"(?V1)[[{_BRAHMIC_CLASS}]&&[\p{{L}}\p{{N}}\p{{M}}]‌‍]+"),
    ),
)

# Precomposed letters that Unicode decomposition cannot reach. NFD turns "é"
# into "e" plus a combining mark, but "đ" and "ø" are atomic code points, so a
# reader typing "Duc Chua Troi" would still miss "Ðức Chúa Trời" without this.
_PRECOMPOSED_FOLD: Final = str.maketrans(
    {
        "đ": "d", "Đ": "D", "ð": "d", "Ð": "D",
        "ø": "o", "Ø": "O", "œ": "oe", "Œ": "OE",
        "æ": "ae", "Æ": "AE", "ł": "l", "Ł": "L",
        "ħ": "h", "Ħ": "H", "ı": "i", "İ": "I",
        "ŧ": "t", "Ŧ": "T", "ŋ": "n", "Ŋ": "N",
        "ẞ": "SS", "þ": "th", "Þ": "TH",
    }
)

# Closed-class particles that attach to the front of an abjad word. Indexing the
# stem alongside the written form is what makes a search for "אור" find
# "וְהָאוֹר" and a search for "بدء" find "الْبَدْءِ", which is what a reader means.
_HEBREW_PROCLITICS: Final = ("ו", "ה", "ב", "ל", "כ", "מ", "ש", "וה", "וב", "ול", "וכ", "ומ", "וש")
_ARABIC_PROCLITICS: Final = ("ال", "و", "ف", "ب", "ل", "ك", "وال", "فال", "بال", "لل", "كال")
# Hebrew and Arabic roots are overwhelmingly triliteral. Requiring three
# remaining letters stops the stripper from inventing a stem out of a word that
# merely begins with a particle letter, such as Hebrew "ברא" or Arabic "الله".
_MIN_ABJAD_STEM: Final = 3

_MAX_GRAM: Final = 2


@dataclass(frozen=True, slots=True)
class Token:
    """One indexable unit and where it sits in the verse.

    ``position`` counts units within the verse and is what phrase, proximity
    and continuous-script adjacency checks compare. ``family`` records which
    analyser produced the token so the engine can apply the right match rule
    without re-deriving the script.
    """

    term: str
    position: int
    family: ScriptFamily
    stem: bool = False


def normalize_text(text: str) -> str:
    """Return text in the canonical form every other function here assumes."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def casefold_text(text: str) -> str:
    return text.casefold()


def fold_marks(text: str) -> str:
    """Remove combining marks and fold precomposed letters to their base.

    Applied to alphabetic and abjad text, where marks are accents or optional
    vowel pointing. Never applied to Brahmic or continuous text, where marks
    carry vowels that change the word.
    """
    decomposed = unicodedata.normalize("NFD", text.translate(_PRECOMPOSED_FOLD))
    stripped = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    return unicodedata.normalize("NFC", stripped)


def script_census(texts: Sequence[str], sample: int = 512) -> dict[ScriptFamily, int]:
    """Count letters per family across a sample of a translation's verses.

    Used once per corpus to describe what a translation actually contains,
    which is more reliable than its declared language tag: the API carries
    ``zh`` with no script subtag for one Chinese translation, and blank
    language names for several others.
    """
    counts: dict[ScriptFamily, int] = dict.fromkeys(ScriptFamily, 0)
    if not texts:
        return counts
    step = max(1, len(texts) // sample) if len(texts) > sample else 1
    for index in range(0, len(texts), step):
        for family, characters in _classify_runs(normalize_text(texts[index])):
            counts[family] += len(characters)
    return counts


def classify_text(text: str) -> ScriptFamily:
    """Return the family that dominates one string, for reporting and tests."""
    counts = script_census([text])
    return max(counts, key=lambda family: counts[family])


def _family_of(character: str) -> ScriptFamily:
    if _CONTINUOUS_CHAR.match(character):
        return ScriptFamily.CONTINUOUS
    if _ABJAD_CHAR.match(character):
        return ScriptFamily.ABJAD
    if _BRAHMIC_CHAR.match(character):
        return ScriptFamily.BRAHMIC
    return ScriptFamily.ALPHABETIC


def _classify_runs(text: str) -> Iterator[tuple[ScriptFamily, str]]:
    """Split text into maximal single-family runs, skipping separators."""
    position = 0
    length = len(text)
    while position < length:
        character = text[position]
        if not _LETTER.match(character) and not unicodedata.combining(character):
            position += 1
            continue
        family = _family_of(character)
        pattern = next(
            (candidate for group, candidate in _RUN_PATTERNS if group is family),
            None,
        )
        if pattern is None:
            match = _WORD.match(text, position)
            if match is None:
                position += 1
                continue
            yield ScriptFamily.ALPHABETIC, match.group()
            position = match.end()
            continue
        match = pattern.match(text, position)
        if match is None:
            position += 1
            continue
        yield family, match.group()
        position = match.end()


class Analyzer:
    """Turn normalized text into tokens under one case and folding policy.

    One analyzer serves both sides of a search. The corpus is analysed once at
    index time and the query is analysed the same way at request time, so a
    query term can only match what the same rules produced from the verse.
    """

    __slots__ = ("case_sensitive", "fold_diacritics")

    def __init__(self, case_sensitive: bool = False, fold_diacritics: bool = True) -> None:
        self.case_sensitive = case_sensitive
        self.fold_diacritics = fold_diacritics

    def key(self) -> tuple[bool, bool]:
        return (self.case_sensitive, self.fold_diacritics)

    def prepare(self, text: str) -> str:
        """Return the normalized verse text that token offsets refer to."""
        value = normalize_text(text)
        return value if self.case_sensitive else casefold_text(value)

    def tokens(self, text: str) -> list[Token]:
        """Analyse one verse or query into positioned tokens."""
        produced: list[Token] = []
        position = 0
        for family, run in _classify_runs(self.prepare(text)):
            if family is ScriptFamily.CONTINUOUS:
                position = self._continuous_tokens(run, position, produced)
            elif family is ScriptFamily.ABJAD:
                position = self._abjad_tokens(run, position, produced)
            elif family is ScriptFamily.BRAHMIC:
                produced.append(Token(run, position, family))
                position += 1
            else:
                position = self._alphabetic_tokens(run, position, produced)
        return produced

    def terms(self, text: str) -> list[str]:
        """Return only the distinct index keys, preserving first-seen order."""
        return list(dict.fromkeys(token.term for token in self.tokens(text)))

    def runs(self, text: str) -> list[tuple[ScriptFamily, str]]:
        """Split text into the units a reader would consider separate things.

        Space-delimited scripts yield one entry per word; continuous scripts
        yield one entry per uninterrupted run. Query parsing uses this so a
        query mixing scripts is handled part by part rather than forcing one
        strategy onto the whole string.
        """
        produced: list[tuple[ScriptFamily, str]] = []
        for family, run in _classify_runs(self.prepare(text)):
            if family is ScriptFamily.ALPHABETIC:
                candidates = [self._fold(match.group()) for match in _WORD.finditer(run)]
            elif family is ScriptFamily.ABJAD:
                candidates = [self._fold(run)]
            else:
                candidates = [run]
            # Folding can empty a run that held nothing but combining marks. A
            # unit with no letter or number is not something a reader asked for,
            # and letting one through would silently match every verse.
            produced.extend(
                (family, value) for value in candidates if _LETTER.search(value)
            )
        return produced

    def _alphabetic_tokens(
        self, run: str, position: int, produced: list[Token]
    ) -> int:
        for match in _WORD.finditer(run):
            word = match.group()
            produced.append(
                Token(self._fold(word), position, ScriptFamily.ALPHABETIC)
            )
            position += 1
        return position

    def _abjad_tokens(self, run: str, position: int, produced: list[Token]) -> int:
        word = self._fold(run)
        produced.append(Token(word, position, ScriptFamily.ABJAD))
        stem = _strip_proclitic(word)
        if stem is not None:
            # A stem token shares its position with the written form: it is the
            # same word, reachable by the shorter thing a reader types.
            produced.append(Token(stem, position, ScriptFamily.ABJAD, stem=True))
        return position + 1

    def _continuous_tokens(
        self, run: str, position: int, produced: list[Token]
    ) -> int:
        graphemes = _GRAPHEME.findall(run)
        for offset, grapheme in enumerate(graphemes):
            produced.append(
                Token(grapheme, position + offset, ScriptFamily.CONTINUOUS)
            )
            if offset + _MAX_GRAM <= len(graphemes):
                produced.append(
                    Token(
                        "".join(graphemes[offset:offset + _MAX_GRAM]),
                        position + offset,
                        ScriptFamily.CONTINUOUS,
                    )
                )
        return position + len(graphemes)

    def _fold(self, value: str) -> str:
        return fold_marks(value) if self.fold_diacritics else value


def _strip_proclitic(word: str) -> str | None:
    """Return the stem when a closed-class particle is attached, else None."""
    proclitics = _HEBREW_PROCLITICS if _is_hebrew(word) else _ARABIC_PROCLITICS
    for particle in sorted(proclitics, key=len, reverse=True):
        if word.startswith(particle) and len(word) - len(particle) >= _MIN_ABJAD_STEM:
            return word[len(particle):]
    return None


def _is_hebrew(word: str) -> bool:
    return bool(word) and regex.match(r"\p{Script_Extensions=Hebrew}", word[0]) is not None


def continuous_chain(run: str) -> tuple[Token, ...]:
    """Return the tokens that prove a continuous-script run occurs verbatim.

    A run of ``n`` characters is pinned by its ``n - 1`` overlapping bigrams: if
    bigram ``i`` sits at position ``p + i`` for every ``i``, the run occurs at
    ``p``. A single character is pinned by itself. Positions alone settle it, so
    verifying a match never reads the verse text.
    """
    graphemes = _GRAPHEME.findall(run)
    if not graphemes:
        return ()
    if len(graphemes) == 1:
        return (Token(graphemes[0], 0, ScriptFamily.CONTINUOUS),)
    return tuple(
        Token(
            "".join(graphemes[offset:offset + _MAX_GRAM]),
            offset,
            ScriptFamily.CONTINUOUS,
        )
        for offset in range(len(graphemes) - _MAX_GRAM + 1)
    )


def analyzer_for(case_sensitive: bool, fold_diacritics: bool) -> Analyzer:
    return Analyzer(case_sensitive=case_sensitive, fold_diacritics=fold_diacritics)


def normalize_book_name(name: str) -> str:
    """Fold a book name to the form used for translation-native lookups."""
    folded = fold_marks(casefold_text(normalize_text(name)))
    return "".join(folded.replace(".", "").split())
