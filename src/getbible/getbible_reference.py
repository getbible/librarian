import re
from getbible import GetBibleBookNumber
from dataclasses import dataclass


@dataclass
class BookReference:
    book: int
    chapter: int
    verses: list


class GetBibleReference:

    def __init__(self):
        self.__get_book = GetBibleBookNumber()

    def ref(self, reference, translation_code=None):
        # Split at the first colon to separate book from verses, defaulting to chapter 1, verse 1 if not present
        book_chapter, verses_portion = reference.split(':', 1) if ':' in reference else (reference, '1')
        # Try to extract the chapter number from the book_chapter part
        chapter_match = re.search(r'\d+$', book_chapter)
        if chapter_match:
            # If a chapter number is found, extract it and the book name
            chapter_number = int(chapter_match.group())
            book_name = book_chapter[:chapter_match.start()].strip()
        else:
            # If no chapter number is found, default to chapter 1
            chapter_number = 1
            book_name = book_chapter.strip()
        # Retrieve the book number
        book_number = self.__get_book_number(book_name, translation_code)
        if not book_number:
            raise ValueError(f"Book number for '{book_name}' could not be found.")
        # Extract verses
        verses_arr = self.__get_verses_numbers(verses_portion.strip())
        # We return a dataclass (needs Python 3.7+)
        return BookReference(book=int(book_number), chapter=chapter_number, verses=verses_arr)

    def __get_verses_numbers(self, verses):
        if not verses:
            return [1]
        # Process a string of verses into a list
        verse_parts = verses.split(',')
        verse_list = []
        for part in verse_parts:
            if '-' in part:
                range_parts = part.split('-')
                # Ignore if neither start nor end are digits
                if len(range_parts) == 2:
                    start, end = range_parts
                    if start.isdigit() and end.isdigit():
                        verse_list.extend(range(int(start), int(end) + 1))
                    elif start.isdigit():
                        verse_list.append(int(start))
                elif len(range_parts) == 1 and range_parts[0].isdigit():
                    verse_list.append(int(range_parts[0]))
            elif part.isdigit():
                verse_list.append(int(part))
        if not verse_list:
            return [1]
        return verse_list

    def __get_book_number(self, book_name, abbreviation):
        # Retrieve the book number given a translation abbreviation and a book name
        if re.match(r'^[0-9]+$', book_name):
            return book_name
        book_number = self.__get_book.number(book_name, abbreviation)
        return book_number

