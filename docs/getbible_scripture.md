# GetBible Scripture

The `GetBible` package is a Python library designed for efficiently retrieving scripture across various translations.

## Features

- Returns a selected range of referenced scripture passages.

## Installation (pip)

To install the package using pip, see [the documentation](https://git.vdm.dev/getBible/-/packages/pypi/getbible-librarian).

## Installation (git)

To install `GetBible`, you need to clone the repository and install the package manually. Ensure you have Python 3.7 or higher installed.

```bash
git clone https://git.vdm.dev/getBible/librarian.git
cd librarian
pip install .
```

## Usage

### Basic Usage

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

### Using Translation Abbreviations

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
python -m unittest tests.test_getbible
```

## Contributing

Contributions to the `GetBible` class is welcome. Please ensure to follow the coding standards and write tests for new features.

## License

This project is licensed under the GNU GPL v2.0. See the LICENSE file for more details.
