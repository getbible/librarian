from .getbible_reference_trie import GetBibleReferenceTrie
import os


class GetBibleBookNumber:
    def __init__(self):
        self._tries = {}
        self._data_path = os.path.join(os.path.dirname(__file__), 'data')
        self._load_all_translations()

    def _load_translation(self, filename):
        trie = GetBibleReferenceTrie()
        translation_code = filename.split('.')[0]
        try:
            trie.load(os.path.join(self._data_path, filename))
        except IOError as e:
            raise IOError(f"Error loading translation {translation_code}: {e}")
        self._tries[translation_code] = trie

    def _load_all_translations(self):
        for filename in os.listdir(self._data_path):
            if filename.endswith('.json'):
                self._load_translation(filename)

    def number(self, reference, translation_code=None, fallback_translations=None):
        # Default to 'kjv' if no translation code is provided
        if not translation_code or translation_code not in self._tries:
            translation_code = 'kjv'

        translation = self._tries.get(translation_code)
        result = translation.search(reference) if translation else None
        if result:
            return result

        # If 'kjv' is not the original choice, try it next
        if translation_code != 'kjv':
            translation = self._tries.get('kjv')
            result = translation.search(reference) if translation else None
            if result:
                return result

        # Fallback to other translations
        if fallback_translations is None:
            fallback_translations = [code for code in self._tries if code != translation_code]

        for code in fallback_translations:
            translation = self._tries.get(code)
            result = translation.search(reference) if translation else None
            if result:
                return result

        return None

    def dump(self, translation_code, filename):
        if translation_code in self._tries:
            self._tries[translation_code].dump(filename)
        else:
            raise ValueError(f"No data available for translation: {translation_code}")
