# GetBible Reference

The `GetBibleReference` package is a Python library designed for efficiently retrieving the book number, chapter and verses of Bible reference across various translations.

## Features

- Returns well formed book-number, chatper-number, and verse array when given any scripture text reference.

## Installation (pip)

To install the package using pip, see [the documentation](https://git.vdm.dev/getBible/-/packages/pypi/getbible-librarian).

## Installation (git)

To install `GetBibleReference`, you need to clone the repository and install the package manually. Ensure you have Python 3.7 or higher installed.

```bash
git clone https://git.vdm.dev/getBible/librarian.git
cd librarian
pip install .
```

## Usage

### Basic Usage

```python
from getbible import GetBibleReference

# Initialize the class
get = GetBibleReference()

# Find well form reference
reference = get.ref("Genesis 1:1-5")
print(reference)  # Outputs the dataclass [BookReference] { book: int, chapter: int, verses: list }
```

### Using Translation Abbreviations

When utilizing the `GetBibleReference` class to look up a reference, you can use the lowercase abbreviations of the target translation:

```python
reference = get.ref("Genesis 1:1-5", 'kjv')
```

In this code snippet, `"kjv"` is used as the abbreviation for the King James Version to speedup the search.

## Development and Testing

To contribute or run tests, clone the repository and set up a virtual environment:

```bash
git clone https://git.vdm.dev/getBible/librarian.git
cd reference
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`
pip install -e .
```

Run tests using the standard unittest framework:

```bash
python -m unittest tests.test_getbible_reference
```

## Contributing

Contributions to the `GetBibleReference` class is welcome. Please ensure to follow the coding standards and write tests for new features.

## License

This project is licensed under the GNU GPL v2.0. See the LICENSE file for more details.
