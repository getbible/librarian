from .trie_node import TrieNode
import json
import re


class GetBibleReferenceTrie:
    def __init__(self):
        self.root = TrieNode()
        # Updated regex to support Unicode characters
        self.space_removal_regex = re.compile(r'(\d)\s+(\w)', re.UNICODE)

    def _preprocess(self, name):
        # Remove all periods
        processed_name = name.replace('.', '')
        # Process the name considering Unicode characters
        processed_name = self.space_removal_regex.sub(r'\1\2', processed_name)
        return processed_name.lower()

    def _insert(self, book_number, names):
        for name in names:
            processed_name = self._preprocess(name)
            node = self.root
            for char in processed_name:
                node = node.children.setdefault(char, TrieNode())
            node.book_number = book_number

    def search(self, book_name):
        processed_name = self._preprocess(book_name)
        node = self.root
        for char in processed_name:
            node = node.children.get(char)
            if node is None:
                return None
        return node.book_number if node.book_number else None

    def _dump_to_dict(self, node=None, key=''):
        if node is None:
            node = self.root

        result = {}
        if node.book_number is not None:
            result[key] = {'book_number': node.book_number}

        for char, child in node.children.items():
            result.update(self._dump_to_dict(child, key + char))

        return result

    def dump(self, filename):
        trie_dict = self._dump_to_dict()
        with open(filename, 'w') as file:
            json.dump(trie_dict, file, ensure_ascii=False, indent=4)

    def load(self, file_path):
        try:
            with open(file_path, 'r') as file:
                data = json.load(file)
                for book_number, names in data.items():
                    self._insert(book_number, names)
        except IOError as e:
            raise IOError(f"Error loading file {file_path}: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from file {file_path}: {e}")
        except Exception as e:
            raise Exception(f"An error occurred while processing {file_path}: {e}")
