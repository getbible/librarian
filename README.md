# getBible Librarian

The `getBible Librarian` package is a Python library designed for efficiently retrieving the scripture reference across various translations.

## Features

- [Get Scripture](https://git.vdm.dev/getBible/librarian/src/branch/master/docs/getbible_scripture.md)
- [Get Reference](https://git.vdm.dev/getBible/librarian/src/branch/master/docs/getbible_reference.md)
- [Get Book Number](https://git.vdm.dev/getBible/librarian/src/branch/master/docs/getbible_book_number.md)

## Installation (pip)

To install the package using pip, see [the documentation](https://git.vdm.dev/getBible/-/packages/pypi/getbible-librarian).

## Installation (git)

To install `getBible-Librarian`, you need to clone the repository and install the package manually. Ensure you have Python 3.7 or higher installed.

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

Contributions to the `getBible-Librarian` package are welcome. Please ensure to follow the coding standards and write tests for new features.

## License

This project is licensed under the GNU GPL v2.0. See the LICENSE file for more details.

