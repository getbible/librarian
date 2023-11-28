from .getbible_reference_trie import GetBibleReferenceTrie
import os
from typing import Any, List, Optional


class GetBibleBookNumber:
    def __init__(self) -> None:
        """
        Initialize the GetBibleBookNumber class.

        Sets up the class by loading all translation tries from the data directory.
        """
        self.__tries = {}
        self.__data_path = os.path.join(os.path.dirname(__file__), 'data')
        self.__load_all_translations()

    def __load_translation(self, filename: str) -> None:
        """
        Load a translation trie from a specified file.

        :param filename: The name of the file to load.
        :raises IOError: If there is an error loading the file.
        """
        trie = GetBibleReferenceTrie()
        translation_code = filename.split('.')[0]
        try:
            trie.load(os.path.join(self.__data_path, filename))
        except IOError as e:
            raise IOError(f"Error loading translation {translation_code}: {e}")
        self.__tries[translation_code] = trie

    def __load_all_translations(self) -> None:
        """
        Load all translation tries from the data directory.
        """
        for filename in os.listdir(self.__data_path):
            if filename.endswith('.json'):
                self.__load_translation(filename)

    def __valid_book_number(self, number: str) -> Optional[int]:
        """
        Check if the number is a valid book number.
        """
        try:
            num = int(number)
            if 1 <= num <= 83:
                return num
            else:
                return None
        except ValueError:
            # Handle the case where the number cannot be converted to an integer
            return None

    def number(self, reference: str, translation_code: Optional[str] = None,
               fallback_translations: Optional[List[str]] = None) -> Optional[int]:
        """
        Get the book number based on a reference and translation code.

        :param reference: The reference to search for.
        :param translation_code: The code for the translation to use.
        :param fallback_translations: A list of fallback translations to use if necessary.
        :return: The book number as an integer if found, None otherwise.
        """
        if reference.isdigit():
            return self.__valid_book_number(reference)

        if not translation_code or translation_code not in self.__tries:
            translation_code = 'kjv'

        translation = self.__tries.get(translation_code)
        result = translation.search(reference) if translation else None
        if result and result.isdigit():
            return int(result)

        # If 'kjv' is not the original choice, try it next
        if translation_code != 'kjv':
            translation = self.__tries.get('kjv')
            result = translation.search(reference) if translation else None
            if result and result.isdigit():
                return int(result)

        # Fallback to other translations
        if fallback_translations is None:
            fallback_translations = [code for code in self.__tries if code != translation_code]

        for code in fallback_translations:
            translation = self.__tries.get(code)
            result = translation.search(reference) if translation else None
            if result and result.isdigit():
                return int(result)

        return None

    def dump(self, translation_code: str, filename: str) -> None:
        """
        Dump the trie data for a specific translation to a file.

        :param translation_code: The code for the translation.
        :param filename: The name of the file to dump to.
        :raises ValueError: If no data is available for the specified translation.
        """
        if translation_code in self.__tries:
            self.__tries[translation_code].dump(filename)
        else:
            raise ValueError(f"No data available for translation: {translation_code}")
