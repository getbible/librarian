import re
from getbible import GetBibleBookNumber
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class BookReference:
    book: int
    chapter: int
    verses: list
    reference: str


class GetBibleReference:
    def __init__(self):
        self.__get_book = GetBibleBookNumber()
        self.__pattern = re.compile(r'[\w\s,:-]{1,50}', re.UNICODE)
        self.__cache = {}
        self.__cache_limit = 5000

    def ref(self, reference: str, translation_code: Optional[str] = None) -> BookReference:
        """
        Fetch the BookReference from cache or create it if not present.

        :param reference: Scripture reference string.
        :param translation_code: Optional translation code.
        :return: BookReference object.
        :raises ValueError: If reference is invalid.
        """
        sanitized_ref = self.__sanitize(reference)
        if not sanitized_ref:
            raise ValueError(f"Invalid reference '{reference}'.")
        if sanitized_ref not in self.__cache:
            book_ref = self.__book_reference(reference, translation_code)
            if book_ref is None:
                raise ValueError(f"Invalid reference '{reference}'.")
            self.__manage_local_cache(sanitized_ref, book_ref)
        return self.__cache[sanitized_ref]

    def valid(self, reference: str, translation_code: Optional[str] = None) -> bool:
        """
        Validate a scripture reference and check its presence in the cache.

        :param reference: Scripture reference string.
        :param translation_code: Optional translation code.
        :return: True if valid and present, False otherwise.
        """
        sanitized_ref = self.__sanitize(reference)
        if sanitized_ref is None:
            return False
        if sanitized_ref not in self.__cache:
            book_ref = self.__book_reference(reference, translation_code)
            self.__manage_local_cache(sanitized_ref, book_ref)
        return self.__cache[sanitized_ref] is not None

    def __sanitize(self, reference: str) -> Optional[str]:
        """
        Sanitize a scripture reference by validating and escaping it.

        :param reference: The scripture reference to sanitize.
        :return: Sanitized reference or None if invalid.
        """
        if self.__pattern.match(reference):
            return re.escape(reference)
        return None

    def __book_reference(self, reference: str, translation_code: Optional[str] = None) -> Optional[BookReference]:
        """
        Create a BookReference object from a scripture reference.

        :param reference: Scripture reference string.
        :param translation_code: Optional translation code.
        :return: BookReference object or None if invalid.
        """
        try:
            book_chapter, verses_portion = self.__split_reference(reference)
            book_name = self.__extract_book_name(book_chapter)
            book_number = self.__get_book_number(book_name, translation_code)
            if not book_number:
                return None
            verses_arr = self.__get_verses_numbers(verses_portion)
            chapter_number = self.__extract_chapter(book_chapter)
            return BookReference(book=int(book_number), chapter=chapter_number, verses=verses_arr, reference=reference)
        except Exception:
            return None

    def __split_reference(self, reference: str) -> Tuple[str, str]:
        """
        Split a scripture reference into book chapter and verses portion.

        :param reference: Scripture reference string.
        :return: Tuple of book chapter and verses portion.
        """
        return reference.split(':', 1) if ':' in reference else (reference, '1')

    def __extract_chapter(self, book_chapter: str) -> int:
        """
        Extract the chapter number from the book chapter part.

        :param book_chapter: Book chapter part of the reference.
        :return: Extracted chapter number.
        """
        chapter_match = re.search(r'\d+$', book_chapter)
        return int(chapter_match.group()) if chapter_match else 1

    def __extract_book_name(self, book_chapter: str) -> str:
        """
        Extract the book name from the book chapter part.

        :param book_chapter: Book chapter part of the reference.
        :return: Extracted book name.
        """
        if book_chapter.isdigit():
            # If the entire string is numeric, return it as is
            return book_chapter.strip()

        chapter_match = re.search(r'\d+$', book_chapter)
        return book_chapter[:chapter_match.start()].strip() if chapter_match else book_chapter.strip()

    def __get_verses_numbers(self, verses: str) -> list:
        """
        Convert a verses portion of a reference into a list of verse numbers.

        :param verses: Verses portion of the reference.
        :return: List of verse numbers.
        """
        if not verses:
            return [1]
        verse_parts = verses.split(',')
        verse_list = []
        for part in verse_parts:
            if '-' in part:
                range_parts = part.split('-')
                if all(rp.isdigit() for rp in range_parts):
                    start, end = sorted(map(int, range_parts))
                    verse_list.extend(range(start, end + 1))
                elif len(range_parts) == 2 and range_parts[0].isdigit() and not range_parts[1]:
                    verse_list.append(int(range_parts[0]))
                elif len(range_parts) == 2 and range_parts[1].isdigit() and not range_parts[0]:
                    verse_list.append(int(range_parts[1]))
            elif part.isdigit():
                verse_list.append(int(part))
        return verse_list if verse_list else [1]

    def __get_book_number(self, book_name: str, abbreviation: Optional[str]) -> Optional[int]:
        """
        Retrieve the book number given a book name and translation abbreviation.

        :param book_name: Name of the book.
        :param abbreviation: Translation abbreviation.
        :return: Book number or None if not found.
        """
        return self.__get_book.number(book_name, abbreviation)

    def __manage_local_cache(self, key: str, value: Optional[BookReference]):
        """
        Manage the insertion and eviction policy for the cache.

        :param key: The key to insert into the cache.
        :param value: The value to associate with the key.
        """
        if len(self.__cache) >= self.__cache_limit:
            self.__cache.pop(next(iter(self.__cache)))  # Evict the oldest cache item
        self.__cache[key] = value
