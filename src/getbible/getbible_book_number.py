from .getbible_reference_trie import GetBibleReferenceTrie
import os
from typing import List, Optional


class GetBibleBookNumber:
    def __init__(self) -> None:
        """Load the bundled translation tries used to resolve localized book names."""
        self.__tries = {}
        self.__data_path = os.path.join(os.path.dirname(__file__), "data")
        self.__load_all_translations()

    @property
    def translations(self) -> frozenset:
        """Translation identifiers available in the bundled reference data."""
        return frozenset(self.__tries)

    def __load_translation(self, filename: str) -> None:
        trie = GetBibleReferenceTrie()
        translation_code = filename.rsplit(".", 1)[0]
        try:
            trie.load(os.path.join(self.__data_path, filename))
        except IOError as error:
            raise IOError(f"Error loading translation {translation_code}: {error}") from error
        self.__tries[translation_code] = trie

    def __load_all_translations(self) -> None:
        for filename in os.listdir(self.__data_path):
            if filename.endswith(".json"):
                self.__load_translation(filename)

    @staticmethod
    def __valid_book_number(number: str) -> Optional[int]:
        try:
            parsed = int(number)
        except ValueError:
            return None
        return parsed if 1 <= parsed <= 83 else None

    def number(
        self,
        reference: str,
        translation_code: Optional[str] = None,
        fallback_translations: Optional[List[str]] = None,
    ) -> Optional[int]:
        if reference.isdigit():
            return self.__valid_book_number(reference)

        if not translation_code or translation_code not in self.__tries:
            translation_code = "kjv"

        translation = self.__tries.get(translation_code)
        result = translation.search(reference) if translation else None
        if result and result.isdigit():
            return int(result)

        if translation_code != "kjv":
            translation = self.__tries.get("kjv")
            result = translation.search(reference) if translation else None
            if result and result.isdigit():
                return int(result)

        if fallback_translations is None:
            fallback_translations = [code for code in self.__tries if code != translation_code]

        for code in fallback_translations:
            translation = self.__tries.get(code)
            result = translation.search(reference) if translation else None
            if result and result.isdigit():
                return int(result)
        return None

    def dump(self, translation_code: str, filename: str) -> None:
        if translation_code not in self.__tries:
            raise ValueError(f"No data available for translation: {translation_code}")
        self.__tries[translation_code].dump(filename)
