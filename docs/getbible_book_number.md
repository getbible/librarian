# getBible Book Number

The `GetBibleBookNumber` package is a Python library designed for efficiently retrieving the book number of Bible references across various translations. It utilizes a Trie data structure to store and search through a comprehensive list of book references. This package is particularly useful for applications dealing with biblical texts where quick and accurate reference to book numbers is needed.

## Features

- Supports multiple Bible translations. (57)
- Efficient search using Trie data structure.
- Dynamically loads translation data from JSON files.
- Provides functionality to dump Trie data into a JSON file for review.
- Fallback search mechanisms for comprehensive reference coverage.

## Installation

To install `GetBibleBookNumber`, you need to clone the repository and install the package manually. Ensure you have Python 3.7 or higher installed.

```bash
git clone https://git.vdm.dev/getBible/booknumber.git
cd booknumber
pip install .
```

## Usage

### Basic Usage

```python
from getbible import GetBibleBookNumber

# Initialize the class
get_book = GetBibleBookNumber()

# Find a book number
book_number = get_book.number("Genesis")
print(book_number)  # Outputs the book number of "Genesis"
```

## Available Translations and Abbreviations

The `GetBibleBookNumber` package supports a range of Bible translations, each identified by a lowercase abbreviation. These abbreviations and the corresponding translation data are stored in the `data` folder.

### Finding Translation Abbreviations

To find the available translation abbreviations:

1. Go to the `data` directory in the package.
2. Each JSON file in this directory corresponds to a different translation.
3. The file name (without the `.json` extension) represents the abbreviation for that translation.

For instance, if you find a file named `kjv.json`, then `kjv` is the abbreviation for the King James Version translation.

### Using Translation Abbreviations

When utilizing the `GetBibleBookNumber` class to look up a book number, you should use these lowercase abbreviations:

```python
book_number = get_book.number("Gen", "kjv", ["aov", "swahili"])
```

In this code snippet, `"kjv"` is used as the abbreviation for the King James Version, `"aov"` for the Afrikaans Ou Vertaaling, and `"swahili"` for the Swahili Version.

## Development and Testing

To contribute or run tests, clone the repository and set up a virtual environment:

```bash
git clone https://git.vdm.dev/getBible/librarian.git
cd librarian
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`
pip install -e .
```

Run tests using the standard unittest framework:

```bash
python -m unittest tests.test_getbible_book_number
```

## Contributing

Contributions to the `GetBibleBookNumber` class is welcome. Please ensure to follow the coding standards and write tests for new features.

## License

This project is licensed under the GNU GPL v2.0. See the LICENSE file for more details.

