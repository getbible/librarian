"""Scripture-reference parsing and bounded reference caching."""

from __future__ import annotations

import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass

from .getbible_book_number import GetBibleBookNumber


@dataclass
class BookReference:
    book: int
    chapter: int
    verses: list[int]
    reference: str


class GetBibleReference:
    """Resolve human scripture references into canonical book coordinates."""

    _ALLOWED_PUNCTUATION = frozenset(" ,:-.'’")

    def __init__(self, cache_limit: int | None = 5000) -> None:
        if cache_limit is not None and (
            not isinstance(cache_limit, int)
            or isinstance(cache_limit, bool)
            or cache_limit < 0
        ):
            raise ValueError("cache_limit must be a non-negative integer or null.")
        self.__get_book = GetBibleBookNumber()
        self.__cache: OrderedDict[tuple[str, str], BookReference | None] = OrderedDict()
        self.__cache_limit = cache_limit
        self.__cache_guard = threading.Lock()
        self.__cache_hits = 0
        self.__cache_misses = 0
        self.__cache_evictions = 0

    def ref(self, reference: str, translation_code: str | None = None) -> BookReference:
        """Return a parsed reference or raise :class:`ValueError`."""
        normalized = self.__sanitize(reference)
        if normalized is None:
            raise ValueError(f"Invalid reference '{reference}'.")

        key = ((translation_code or "").casefold(), normalized.casefold())
        with self.__cache_guard:
            if key in self.__cache:
                cached = self.__cache.pop(key)
                self.__cache[key] = cached
                self.__cache_hits += 1
                found = True
            else:
                self.__cache_misses += 1
                found = False
        if not found:
            resolved = self.__book_reference(reference, normalized, translation_code)
            with self.__cache_guard:
                if key in self.__cache:
                    cached = self.__cache.pop(key)
                    self.__cache[key] = cached
                else:
                    cached = resolved
                    self.__manage_local_cache(key, cached)

        if cached is None:
            raise ValueError(f"Invalid reference '{reference}'.")
        return cached

    def valid(self, reference: str, translation_code: str | None = None) -> bool:
        """Return whether ``reference`` can be resolved."""
        try:
            self.ref(reference, translation_code)
            return True
        except ValueError:
            return False

    def book_number(
        self, reference: str, translation_code: str | None = None
    ) -> int | None:
        """Resolve a book name or number using the configured alias tries."""
        return self.__get_book.number(reference, translation_code)

    def cache_info(self) -> dict[str, int | None]:
        """Return reference-cache size, limit, and counters."""
        with self.__cache_guard:
            return {
                "size": len(self.__cache),
                "limit": self.__cache_limit,
                "hits": self.__cache_hits,
                "misses": self.__cache_misses,
                "evictions": self.__cache_evictions,
            }

    def __sanitize(self, reference: str) -> str | None:
        if not isinstance(reference, str):
            return None
        normalized = unicodedata.normalize("NFC", reference.strip())
        if not normalized or len(normalized) > 100 or normalized.count(":") > 1:
            return None

        for character in normalized:
            category = unicodedata.category(character)
            if category[0] in {"L", "M", "N"}:
                continue
            if character in self._ALLOWED_PUNCTUATION:
                continue
            return None
        return normalized

    def __book_reference(
        self,
        original_reference: str,
        normalized_reference: str,
        translation_code: str | None = None,
    ) -> BookReference | None:
        book_chapter, verses_portion = self.__split_reference(normalized_reference)
        book_name = self.__extract_book_name(book_chapter)
        book_number = self.__get_book.number(book_name, translation_code)
        if book_number is None:
            return None

        chapter_number = self.__extract_chapter(book_chapter)
        verses = self.__get_verses_numbers(verses_portion)
        if chapter_number is None or verses is None:
            return None

        return BookReference(
            book=book_number,
            chapter=chapter_number,
            verses=verses,
            reference=original_reference,
        )

    @staticmethod
    def __split_reference(reference: str) -> tuple[str, str]:
        return reference.split(':', 1) if ':' in reference else (reference, '1')

    @staticmethod
    def __extract_chapter(book_chapter: str) -> int | None:
        digits = []
        for character in reversed(book_chapter):
            if not character.isdigit():
                break
            digits.append(character)
        if not digits:
            return 1
        chapter = int("".join(reversed(digits)))
        return chapter if chapter > 0 else None

    @staticmethod
    def __extract_book_name(book_chapter: str) -> str:
        if book_chapter.isdigit():
            return book_chapter.strip()
        index = len(book_chapter)
        while index > 0 and book_chapter[index - 1].isdigit():
            index -= 1
        return book_chapter[:index].strip() if index < len(book_chapter) else book_chapter.strip()

    @staticmethod
    def __get_verses_numbers(verses: str) -> list[int] | None:
        if not verses:
            return [1]

        verse_list: list[int] = []
        for part in verses.split(','):
            part = part.strip()
            if not part:
                return None
            if '-' not in part:
                if not part.isdigit() or int(part) < 1:
                    return None
                verse_list.append(int(part))
                continue

            if part.count('-') != 1:
                return None
            start_text, end_text = part.split('-', 1)
            if start_text and end_text:
                if not start_text.isdigit() or not end_text.isdigit():
                    return None
                start, end = sorted((int(start_text), int(end_text)))
                if start < 1:
                    return None
                verse_list.extend(range(start, end + 1))
            elif start_text.isdigit() and int(start_text) > 0:
                verse_list.append(int(start_text))
            elif end_text.isdigit() and int(end_text) > 0:
                verse_list.append(int(end_text))
            else:
                return None

        return list(dict.fromkeys(verse_list)) if verse_list else None

    def __manage_local_cache(
        self,
        key: tuple[str, str],
        value: BookReference | None,
    ) -> None:
        if self.__cache_limit == 0:
            return
        if (
            self.__cache_limit is not None
            and len(self.__cache) >= self.__cache_limit
        ):
            self.__cache.popitem(last=False)
            self.__cache_evictions += 1
        self.__cache[key] = value
