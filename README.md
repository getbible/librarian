# getBible Librarian

[![Stable Librarian](https://github.com/getbible/librarian/actions/workflows/stable-librarian.yml/badge.svg)](https://github.com/getbible/librarian/actions/workflows/stable-librarian.yml)
[![GetBible Librarian](https://img.shields.io/pypi/v/getbible?style=flat-square)](https://pypi.org/project/getbible/)

The `getBible` Librarian package is a Python library designed for efficiently retrieving the scripture reference across various translations.

## Installation

```bash
pip install getbible
```
> see package on [pypi](https://pypi.org/project/getbible)

## Features

### Get Scripture

```python
import json
from getbible import GetBible

# Initialize the class
getbible = GetBible()

# Get the scripture as JSON
scripture_json = getbible.scripture("Genesis 1:1")
print(scripture_json)  # Outputs the JSON scripture as a string.

# Get the scripture as dictionary
scripture_dict = getbible.select("Genesis 1:1")
print(json.dumps(scripture_dict, indent=4))  # Pretty-prints the dictionary.
```

#### Using Translation Abbreviations

When utilizing the `GetBible` class to look up a reference, you can use the lowercase abbreviations of the target translation:

```python
import json
from getbible import GetBible

# Initialize the class
getbible = GetBible()

scripture = getbible.select("Genesis 1:1-5", 'aov')
print(json.dumps(scripture, indent=4))  # Pretty-prints the dictionary.
```

In this code snippet, `"aov"` is used as the abbreviation for the Afrikaans Ou Vertaaling.

### Get Reference

```python
from getbible import GetBibleReference

# Initialize the class
get = GetBibleReference()

# Find well form reference
reference = get.ref("Genesis 1:1-5")
print(reference)  # Outputs the dataclass [BookReference] { book: int, chapter: int, verses: list }
```

#### Using Translation Abbreviations

When utilizing the `GetBibleReference` class to look up a reference, you can use the lowercase abbreviations of the target translation:

```python
from getbible import GetBibleReference

# Initialize the class
get = GetBibleReference()

reference = get.ref("Genesis 1:1-5", 'kjv')
```

In this code snippet, `"kjv"` is used as the abbreviation for the King James Version to speedup the search.

### Get Book Number

```python
from getbible import GetBibleBookNumber

# Initialize the class
get_book = GetBibleBookNumber()

# Find a book number
book_number = get_book.number("Genesis")
print(book_number)  # Outputs the book number of "Genesis" = 1
```

#### Available Translations and Abbreviations

The `GetBibleBookNumber` package supports a range of Bible translations, each identified by a lowercase abbreviation. These abbreviations and the corresponding translation data are stored in the `data` folder.

#### Finding Translation Abbreviations

To find the available translation abbreviations:

1. Go to the `data` [directory in the package](https://git.vdm.dev/getBible/librarian/src/branch/master/src/getbible/data).
2. Each JSON file in this directory corresponds to a different translation.
3. The file name (without the `.json` extension) represents the abbreviation for that translation.

For instance, if you find a file named `kjv.json`, then `kjv` is the abbreviation for the King James Version translation.

#### Using Translation Abbreviations

When utilizing the `GetBibleBookNumber` class to look up a book number, you should use these lowercase abbreviations:

```python
book_number = get_book.number("Gen", "kjv", ["aov", "swahili"])
```

In this code snippet, `"kjv"` is used as the abbreviation for the King James Version, `"aov"` for the Afrikaans Ou Vertaaling, and `"swahili"` for the Swahili Version.

## Source Installation (git)

To install `getBible` Librarian, you need to clone the repository and install the package manually. Ensure you have Python 3.7 or higher installed.

```bash
git clone https://git.vdm.dev/getBible/librarian.git
cd librarian
pip install .
```

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
python -m unittest
```

## Contributing

Contributions to the `getbible` Librarian package are welcome. Please ensure to follow the coding standards and write tests for new features.

## License

This project is licensed under the GNU GPL v2.0. See the LICENSE file for more details.

