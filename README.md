# GetBible Librarian

[![Stable Librarian](https://github.com/getbible/librarian/actions/workflows/stable-librarian.yml/badge.svg)](https://github.com/getbible/librarian/actions/workflows/stable-librarian.yml)
[![PyPI](https://img.shields.io/pypi/v/getbible?style=flat-square)](https://pypi.org/project/getbible/)

`getbible` retrieves Scripture from a GetBible v2 repository and parses localized Bible references. Version 1.2 adds strict input validation, bounded work, typed failures, explicit network timeouts and retries, and bounded thread-safe caches.

## Installation

```bash
python -m pip install getbible
```

Python 3.9 or newer is required.

## Basic use

```python
from getbible import GetBible

with GetBible() as scriptures:
    result = scriptures.select("John 3:16", "kjv")
    print(result)
```

Multiple references are separated with semicolons:

```python
result = scriptures.select("Genesis 1:1-3;John 1:1", "kjv")
```

The default safety budget is eight references and 200 selected verses per request. These limits are configurable, but callers exposed to untrusted input should normally reduce them rather than increase them.

```python
scriptures = GetBible(
    max_references=8,
    max_total_verses=100,
    connect_timeout=3.05,
    read_timeout=10.0,
    retries=2,
)
```

## Local repository

A local GetBible v2 data tree removes the network dependency:

```python
scriptures = GetBible(repo_path="/srv/getbible-data", version="v2")
```

`repo_path` must contain paths such as `v2/kjv/books.json` and `v2/kjv/43/3.json`.

## Validation

Reference parsing consumes the complete input. Malformed suffixes, dangling ranges, reversed ranges, excessive ranges, control characters, and unknown books are rejected rather than silently converted to another verse.

```python
from getbible import GetBibleReference, InvalidReferenceError

parser = GetBibleReference(max_verses=100)

try:
    reference = parser.ref("1 John 3:16,19-21", "kjv")
except InvalidReferenceError as error:
    print(error)
```

`GetBible.available_translations` returns the locally known translation codes without performing network I/O. `valid_translation()` first requires membership in that local set and only then checks the configured repository.

## Typed errors

```python
from getbible import (
    DataValidationError,
    InvalidReferenceError,
    ScriptureNotFoundError,
    TranslationNotFoundError,
    UpstreamUnavailableError,
)
```

Applications should convert these exceptions into their own user-safe messages. Do not expose raw exception details from unexpected failures to public users.

## Development

```bash
git clone https://github.com/getbible/librarian.git
cd librarian
python -m venv .venv
source .venv/bin/activate
python -m pip install -e . -r requirements-dev.txt
python -m unittest discover -s tests -v
ruff check src tests
bandit -q -r src/getbible
pip-audit -r requirements.txt
```

The default test suite is offline and deterministic. Network integration checks should be run separately against a controlled GetBible endpoint.

## Security

Please report vulnerabilities privately as described in [SECURITY.md](SECURITY.md). The parser and client have hard safety limits, but every public application must also apply user, chat, and global rate limits.

## License

GNU GPL v2.0. See [LICENSE](LICENSE).
