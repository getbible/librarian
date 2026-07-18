"""Strict, bounded parsing of Bible references."""

from collections import OrderedDict
from dataclasses import dataclass
import re
import threading
import unicodedata
from typing import List, Optional, Tuple

from getbible.errors import InvalidReferenceError
from getbible.getbible_book_number import GetBibleBookNumber


@dataclass(frozen=True)
class BookReference:
    """Canonical location selected by one user reference."""

    book: int
    chapter: int
    verses: List[int]
    reference: str


class GetBibleReference:
    """Parse references without accepting partial or computationally unbounded input."""

    DEFAULT_MAX_REFERENCE_LENGTH = 128
    DEFAULT_MAX_VERSES = 200
    DEFAULT_MAX_CHAPTER = 999
    DEFAULT_MAX_VERSE = 999
    DEFAULT_CACHE_LIMIT = 5000

    _VERSE_LIST = re.compile(
        r"\d{1,4}(?:\s*-\s*\d{1,4})?"
        r"(?:\s*,\s*\d{1,4}(?:\s*-\s*\d{1,4})?)*"
    )
    _TRAILING_CHAPTER = re.compile(r"(?P<chapter>\d{1,4})\s*$")
    _SPACE = re.compile(r"\s+")
    _ALLOWED_BOOK_PUNCTUATION = frozenset({" ", ".", "-", "'", "’", "ʻ", "ʼ", "־"})

    def __init__(
        self,
        max_reference_length: int = DEFAULT_MAX_REFERENCE_LENGTH,
        max_verses: int = DEFAULT_MAX_VERSES,
        max_chapter: int = DEFAULT_MAX_CHAPTER,
        max_verse: int = DEFAULT_MAX_VERSE,
        cache_limit: int = DEFAULT_CACHE_LIMIT,
        book_number_resolver: Optional[GetBibleBookNumber] = None,
    ) -> None:
        if min(max_reference_length, max_verses, max_chapter, max_verse, cache_limit) < 1:
            raise ValueError("Parser limits must all be positive integers.")

        self.__get_book = book_number_resolver or GetBibleBookNumber()
        self.__max_reference_length = max_reference_length
        self.__max_verses = max_verses
        self.__max_chapter = max_chapter
        self.__max_verse = max_verse
        self.__cache_limit = cache_limit
        self.__cache = OrderedDict()  # type: OrderedDict[str, BookReference]
        self.__cache_lock = threading.RLock()

    @property
    def available_translations(self) -> frozenset:
        """Return translation identifiers known by the bundled reference data."""

        translations = getattr(self.__get_book, "translations", frozenset())
        return frozenset(translations)

    def ref(self, reference: str, translation_code: Optional[str] = None) -> BookReference:
        """Return a bounded canonical reference or raise ``InvalidReferenceError``."""

        normalized_reference = self.__normalize_input(reference)
        translation_key = (translation_code or "").strip().casefold()
        cache_key = f"{translation_key}:{normalized_reference.casefold()}"

        with self.__cache_lock:
            cached = self.__cache.get(cache_key)
            if cached is not None:
                self.__cache.move_to_end(cache_key)
                return cached

        book_name, chapter, verses = self.__parse(normalized_reference)
        book_number = self.__get_book.number(book_name, translation_code)
        if not book_number:
            raise InvalidReferenceError(f"Invalid reference '{reference}'.")

        parsed = BookReference(
            book=int(book_number),
            chapter=chapter,
            verses=verses,
            reference=normalized_reference,
        )
        with self.__cache_lock:
            self.__cache[cache_key] = parsed
            self.__cache.move_to_end(cache_key)
            while len(self.__cache) > self.__cache_limit:
                self.__cache.popitem(last=False)
        return parsed

    def valid(self, reference: str, translation_code: Optional[str] = None) -> bool:
        """Return ``True`` only when the complete input parses successfully."""

        try:
            self.ref(reference, translation_code)
        except (InvalidReferenceError, TypeError, ValueError):
            return False
        return True

    def __normalize_input(self, reference: str) -> str:
        if not isinstance(reference, str):
            raise InvalidReferenceError("Reference must be text.")
        normalized = unicodedata.normalize("NFC", reference).strip()
        if not normalized or len(normalized) > self.__max_reference_length:
            raise InvalidReferenceError(f"Invalid reference '{reference}'.")
        if normalized.count(":") > 1:
            raise InvalidReferenceError(f"Invalid reference '{reference}'.")
        if any(unicodedata.category(character).startswith("C") for character in normalized):
            raise InvalidReferenceError(f"Invalid reference '{reference}'.")
        return normalized

    def __parse(self, reference: str) -> Tuple[str, int, List[int]]:
        if ":" in reference:
            book_chapter, verses_portion = reference.rsplit(":", 1)
            if not self._VERSE_LIST.fullmatch(verses_portion.strip()):
                raise InvalidReferenceError(f"Invalid reference '{reference}'.")
            verses = self.__parse_verses(verses_portion)
        else:
            book_chapter = reference
            verses = [1]

        book_name, chapter = self.__parse_book_and_chapter(book_chapter, has_verse=":" in reference)
        self.__validate_book_name(book_name, reference)
        return book_name, chapter, verses

    def __parse_book_and_chapter(self, value: str, has_verse: bool) -> Tuple[str, int]:
        value = value.strip()
        if not value:
            raise InvalidReferenceError("Reference is missing a book name.")

        # A bare number is a numeric book identifier with the default chapter.
        if value.isdigit() and not has_verse:
            return value, 1

        match = self._TRAILING_CHAPTER.search(value)
        if match:
            prefix = value[: match.start()].strip()
            if prefix:
                chapter = int(match.group("chapter"))
                if chapter < 1 or chapter > self.__max_chapter:
                    raise InvalidReferenceError(f"Chapter must be between 1 and {self.__max_chapter}.")
                return self._SPACE.sub(" ", prefix), chapter

        if has_verse:
            # ``Genesis:1`` is accepted as book Genesis, chapter 1. A numeric form
            # such as ``1:1`` means numeric book 1, chapter 1.
            if value.isdigit():
                return value, 1
            return self._SPACE.sub(" ", value), 1

        return self._SPACE.sub(" ", value), 1

    def __validate_book_name(self, book_name: str, original_reference: str) -> None:
        if not book_name:
            raise InvalidReferenceError(f"Invalid reference '{original_reference}'.")
        for character in book_name:
            category = unicodedata.category(character)
            if category[0] in {"L", "M", "N"} or character in self._ALLOWED_BOOK_PUNCTUATION:
                continue
            raise InvalidReferenceError(f"Invalid reference '{original_reference}'.")

    def __parse_verses(self, value: str) -> List[int]:
        verses = []  # type: List[int]
        seen = set()
        for part in value.split(","):
            part = part.strip()
            if "-" in part:
                start_text, end_text = (component.strip() for component in part.split("-", 1))
                start = self.__validate_verse_number(start_text)
                end = self.__validate_verse_number(end_text)
                if start > end:
                    raise InvalidReferenceError("Verse ranges must be in ascending order.")
                range_size = end - start + 1
                if range_size > self.__max_verses or len(verses) + range_size > self.__max_verses:
                    raise InvalidReferenceError(
                        f"A reference may select at most {self.__max_verses} verses."
                    )
                candidates = range(start, end + 1)
            else:
                candidates = (self.__validate_verse_number(part),)

            for verse in candidates:
                if verse not in seen:
                    seen.add(verse)
                    verses.append(verse)
                    if len(verses) > self.__max_verses:
                        raise InvalidReferenceError(
                            f"A reference may select at most {self.__max_verses} verses."
                        )

        if not verses:
            raise InvalidReferenceError("A reference must select at least one verse.")
        return verses

    def __validate_verse_number(self, value: str) -> int:
        if not value.isdigit():
            raise InvalidReferenceError("Verse numbers must be positive integers.")
        verse = int(value)
        if verse < 1 or verse > self.__max_verse:
            raise InvalidReferenceError(f"Verse must be between 1 and {self.__max_verse}.")
        return verse
