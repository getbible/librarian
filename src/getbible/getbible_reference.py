"""Scripture-reference parsing and bounded reference caching."""

from __future__ import annotations

import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass

from .exceptions import ReferenceValidationError, RequestLimitError
from .getbible_book_number import GetBibleBookNumber


@dataclass
class BookReference:
    book: int
    chapter: int
    verses: list[int]
    reference: str


class GetBibleReference:
    """Resolve human scripture references into canonical book coordinates.

    Parsing is deliberately bounded before any range is materialized.  The
    defaults cover every canonical Bible chapter while preventing an attacker
    from turning a reference into an arbitrarily large Python list.
    """

    _ALLOWED_PUNCTUATION = frozenset(" ,:-.'’")

    def __init__(
        self,
        cache_limit: int | None = 5000,
        *,
        max_reference_length: int = 100,
        max_verses: int = 200,
        max_verse_number: int = 1000,
    ) -> None:
        if cache_limit is not None and (
            not isinstance(cache_limit, int)
            or isinstance(cache_limit, bool)
            or cache_limit < 0
        ):
            raise ValueError("cache_limit must be a non-negative integer or null.")
        self.__max_reference_length = self.__positive_limit(
            "max_reference_length", max_reference_length
        )
        self.__max_verses = self.__positive_limit("max_verses", max_verses)
        self.__max_verse_number = self.__positive_limit(
            "max_verse_number", max_verse_number
        )
        self.__get_book = GetBibleBookNumber()
        self.__cache: OrderedDict[tuple[str, str], BookReference | None] = OrderedDict()
        self.__cache_limit = cache_limit
        self.__cache_guard = threading.Lock()
        self.__cache_hits = 0
        self.__cache_misses = 0
        self.__cache_evictions = 0

    def ref(self, reference: str, translation_code: str | None = None) -> BookReference:
        """Return a parsed reference or raise a typed validation exception."""
        normalized = self.__sanitize(reference)
        if normalized is None:
            raise ReferenceValidationError(f"Invalid reference '{reference}'.")

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
            raise ReferenceValidationError(f"Invalid reference '{reference}'.")
        # Do not expose the mutable list held by the cache to callers.
        return BookReference(
            book=cached.book,
            chapter=cached.chapter,
            verses=list(cached.verses),
            reference=cached.reference,
        )

    def valid(self, reference: str, translation_code: str | None = None) -> bool:
        """Return whether ``reference`` can be resolved within configured limits."""
        try:
            self.ref(reference, translation_code)
            return True
        except ReferenceValidationError:
            return False

    def book_number(
        self, reference: str, translation_code: str | None = None
    ) -> int | None:
        """Resolve a book name or number using the configured alias tries."""
        return self.__get_book.number(reference, translation_code)

    def cache_info(self) -> dict[str, int | None]:
        """Return reference-cache size, limits, and counters."""
        with self.__cache_guard:
            return {
                "size": len(self.__cache),
                "limit": self.__cache_limit,
                "hits": self.__cache_hits,
                "misses": self.__cache_misses,
                "evictions": self.__cache_evictions,
                "max_reference_length": self.__max_reference_length,
                "max_verses": self.__max_verses,
                "max_verse_number": self.__max_verse_number,
            }

    def __sanitize(self, reference: str) -> str | None:
        if not isinstance(reference, str):
            return None
        normalized = unicodedata.normalize("NFC", reference.strip())
        if (
            not normalized
            or len(normalized) > self.__max_reference_length
            or normalized.count(":") > 1
        ):
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
        return reference.split(":", 1) if ":" in reference else (reference, "1")

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

    def __get_verses_numbers(self, verses: str) -> list[int] | None:
        if not verses:
            return [1]

        verse_list: list[int] = []
        seen: set[int] = set()
        for part in verses.split(","):
            part = part.strip()
            if not part:
                return None
            if "-" not in part:
                if not part.isdigit():
                    return None
                verse = int(part)
                if verse < 1:
                    return None
                if verse > self.__max_verse_number:
                    raise RequestLimitError(
                        f"Verse numbers cannot exceed {self.__max_verse_number}."
                    )
                self.__append_bounded(verse_list, seen, verse)
                continue

            if part.count("-") != 1:
                return None
            start_text, end_text = part.split("-", 1)
            if start_text and end_text:
                if not start_text.isdigit() or not end_text.isdigit():
                    return None
                start = int(start_text)
                end = int(end_text)
                if start < 1 or end < 1 or start > end:
                    return None
                if start > self.__max_verse_number or end > self.__max_verse_number:
                    raise RequestLimitError(
                        f"Verse numbers cannot exceed {self.__max_verse_number}."
                    )
                range_size = end - start + 1
                if range_size > self.__max_verses or len(seen) + range_size > self.__max_verses:
                    raise RequestLimitError(
                        f"A reference cannot select more than {self.__max_verses} verses."
                    )
                # The range is known to be bounded before it is materialized.
                for verse in range(start, end + 1):
                    self.__append_bounded(verse_list, seen, verse)
            elif start_text.isdigit():
                verse = int(start_text)
                if verse < 1:
                    return None
                if verse > self.__max_verse_number:
                    raise RequestLimitError(
                        f"Verse numbers cannot exceed {self.__max_verse_number}."
                    )
                self.__append_bounded(verse_list, seen, verse)
            elif end_text.isdigit():
                verse = int(end_text)
                if verse < 1:
                    return None
                if verse > self.__max_verse_number:
                    raise RequestLimitError(
                        f"Verse numbers cannot exceed {self.__max_verse_number}."
                    )
                self.__append_bounded(verse_list, seen, verse)
            else:
                return None

        return verse_list if verse_list else None

    def __append_bounded(self, values: list[int], seen: set[int], verse: int) -> None:
        if verse in seen:
            return
        if len(seen) >= self.__max_verses:
            raise RequestLimitError(
                f"A reference cannot select more than {self.__max_verses} verses."
            )
        seen.add(verse)
        values.append(verse)

    def __manage_local_cache(
        self,
        key: tuple[str, str],
        value: BookReference | None,
    ) -> None:
        if self.__cache_limit == 0:
            return
        if self.__cache_limit is not None and len(self.__cache) >= self.__cache_limit:
            self.__cache.popitem(last=False)
            self.__cache_evictions += 1
        self.__cache[key] = value

    @staticmethod
    def __positive_limit(name: str, value: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an integer.")
        if value < 1:
            raise ValueError(f"{name} must be positive.")
        return value
