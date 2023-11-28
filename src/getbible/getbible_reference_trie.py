from .trie_node import TrieNode
import json
import re
from typing import Dict, Optional


class GetBibleReferenceTrie:
    def __init__(self) -> None:
        """
        Initialize the GetBibleReferenceTrie class.

        Sets up the Trie data structure for storing and searching book names.
        """
        self.__root = TrieNode()
        self.__space_removal_regex = re.compile(r'(\d)\s+(\w)', re.UNICODE)

    def __preprocess(self, name: str) -> str:
        """
        Preprocess a book name by removing periods and spaces between numbers and words.

        :param name: The book name to preprocess.
        :return: The processed name in lowercase.
        """
        processed_name = name.replace('.', '')
        processed_name = self.__space_removal_regex.sub(r'\1\2', processed_name)
        return processed_name.lower()

    def __insert(self, book_number: str, names: [str]) -> None:
        """
        Insert a book number with associated names into the Trie.

        :param book_number: The book number to insert.
        :param names: A list of names associated with the book number.
        """
        for name in names:
            processed_name = self.__preprocess(name)
            node = self.__root
            for char in processed_name:
                node = node.children.setdefault(char, TrieNode())
            node.book_number = book_number

    def search(self, book_name: str) -> Optional[str]:
        """
        Search for a book number based on a book name.

        :param book_name: The book name to search for.
        :return: The book number if found, None otherwise.
        """
        processed_name = self.__preprocess(book_name)
        node = self.__root
        for char in processed_name:
            node = node.children.get(char)
            if node is None:
                return None
        return node.book_number if node.book_number else None

    def __dump_to_dict(self, node: Optional[TrieNode] = None, key: str = '') -> Dict[str, Dict]:
        """
        Convert the Trie into a dictionary representation.

        :param node: The current Trie node to process.
        :param key: The current key being constructed.
        :return: Dictionary representation of the Trie.
        """
        if node is None:
            node = self.__root

        result = {}
        if node.book_number is not None:
            result[key] = {'book_number': node.book_number}

        for char, child in node.children.items():
            result.update(self.__dump_to_dict(child, key + char))

        return result

    def dump(self, filename: str) -> None:
        """
        Dump the Trie data to a JSON file.

        :param filename: The filename to dump the data to.
        """
        trie_dict = self.__dump_to_dict()
        with open(filename, 'w') as file:
            json.dump(trie_dict, file, ensure_ascii=False, indent=4)

    def load(self, file_path: str) -> None:
        """
        Load the Trie data from a JSON file.

        :param file_path: The path of the file to load data from.
        :raises IOError: If there is an error opening the file.
        :raises ValueError: If there is an error decoding the JSON data.
        :raises Exception: If any other error occurs.
        """
        try:
            with open(file_path, 'r') as file:
                data = json.load(file)
                for book_number, names in data.items():
                    self.__insert(book_number, names)
        except IOError as e:
            raise IOError(f"Error loading file {file_path}: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from file {file_path}: {e}")
        except Exception as e:
            raise Exception(f"An error occurred while processing {file_path}: {e}")
