# getBible Librarian

[![CI](https://github.com/getbible/librarian/actions/workflows/ci.yml/badge.svg)](https://github.com/getbible/librarian/actions/workflows/ci.yml)
[![Live API Integration](https://github.com/getbible/librarian/actions/workflows/integration.yml/badge.svg)](https://github.com/getbible/librarian/actions/workflows/integration.yml)
[![PyPI](https://img.shields.io/pypi/v/getbible?style=flat-square)](https://pypi.org/project/getbible/)
[![Python](https://img.shields.io/pypi/pyversions/getbible?style=flat-square)](https://pypi.org/project/getbible/)

GetBible Librarian is the Python library used to resolve scripture references, retrieve verses, and perform Unicode-aware searches against GetBible API translations. It supports standalone scripts as well as threaded and multi-process API services.

- Primary project home: <https://git.vdm.dev/getBible/librarian>
- GitHub deployment and releases: <https://github.com/getbible/librarian>
- GetBible API v2: <https://api.getbible.net/v2/translations.json>
- PyPI: <https://pypi.org/project/getbible/>

## Installation

```bash
python -m pip install getbible
```

Python 3.10 or newer is required.

## Retrieve scripture

```python
import json

from getbible import GetBible


bible = GetBible()

selection = bible.select("Genesis 1:1-3;John 3:16", "kjv")
print(json.dumps(selection, ensure_ascii=False, indent=2))

encoded = bible.scripture("Psalm 23:1-6", "kjv")
print(encoded)
```

`select()` returns the established chapter-keyed dictionary. `scripture()` returns the same structure encoded as JSON.

## Search scripture

```python
import json

from getbible import GetBible, SearchBible, SearchLimits


bible = GetBible(
    search_limits=SearchLimits(
        max_work_units=50_000_000,
        max_response_bytes=4 * 1024 * 1024,
        deadline_seconds=5.0,
    )
)
criteria = SearchBible(
    words="all",
    match="whole_word",
    case_sensitive=False,
    scope="new_testament",
    books=("John", "1 John"),
    exclude=("darkness",),
    sort="canonical",
    limit=20,
    offset=0,
)

response = bible.search("word life", "kjv", criteria)
print(json.dumps(response, ensure_ascii=False, indent=2))
```

Search responses contain three top-level objects:

- `query`: normalized criteria, translation metadata, exact total, pagination, SHA, cache state, and deterministic search cost.
- `results`: the same grouped scripture object format returned by `select()`.
- `matches`: ordered per-verse match metadata, including score, occurrences, and matched terms.

This keeps existing scripture templates reusable. With relevance sorting, `matches` is the authoritative cross-chapter order.

Search criteria may also be supplied as a JSON-decoded dictionary:

```python
response = bible.search(
    "faith hope",
    "kjv",
    {
        "words": "phrase",
        "match": "whole_word",
        "scope": "bible",
        "diacritics": "sensitive",
        "limit": 50,
        "offset": 0,
    },
)
```

## Official HTTP services

Librarian powers two independent read-only API services:

```text
GET https://query.getbible.net/v2/{translation}/{reference}
GET https://search.getbible.net/v2/{translation}?q={query}
```

Query uses the lightweight `select()` path and does not expose search. Search
uses `search()` and accepts filtering through URL query parameters; it does not
expose reference routes or POST requests. See
[HTTP GET service integration](docs/API_INTEGRATION.md) for the complete
parameter mapping, response contracts, cache separation, and deployment model.

## Cache behavior

Reference retrieval keeps the lightweight chapter request path. Search downloads the selected full translation once, verifies it against `/v2/{translation}.sha`, and builds a compact in-memory postings index.

By default, full translations are cached under the operating system's user cache directory and checked every seven days. Configure a shared service cache explicitly:

```python
from datetime import timedelta

from getbible import GetBible


bible = GetBible(
    cache_dir="/var/cache/getbible",
    cache_ttl=timedelta(days=7),
    strict_freshness=False,
    require_checksums=True,
)
```

Remote production checksums are required. Full corpora and their independent
books indexes are completely validated before immutable, content-addressed
payloads are atomically committed. A last-known-good translation remains
available during temporary repository or newly published integrity failures
unless `strict_freshness=True`.

Production caches are bounded by default. A service can warm its expected
translation without issuing an artificial query and can expose cache counters to
its internal metrics system:

```python
bible = GetBible(
    cache_dir="/var/cache/getbible",
    search_corpus_limit=4,
    translation_cache_limit=4,
)
bible.warm_translation("kjv")
cache_state = bible.cache_info()
```

Atomically updated local mirrors can coordinate application response caches and
worker-local invalidation with `source_operation()` and
`transition_source()`. See [Cache validation and retention](docs/CACHING.md).

Call `bible.close()` during worker shutdown, or use `GetBible` as a context
manager in short-lived scripts.

## Documentation

- [Usage and reference retrieval](docs/USAGE.md)
- [Search criteria and response contract](docs/SEARCH.md)
- [Separate Query and Search HTTP integration](docs/API_INTEGRATION.md)
- [Cache validation and retention](docs/CACHING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Multi-worker operations](docs/OPERATIONS.md)
- [Development and releases](docs/RELEASING.md)
- [AI and repository guidance](AGENTS.md)

## Source installation

The primary project home remains on VDM Gitea:

```bash
git clone https://git.vdm.dev/getBible/librarian.git
cd librarian
python -m venv .venv
.venv/bin/python -m pip install -e .
```

The GitHub deployment mirror can also be cloned:

```bash
git clone https://github.com/getbible/librarian.git
cd librarian
python -m venv .venv
.venv/bin/python -m pip install -e .
```

## Development

```bash
./scripts/run_release_gate.sh
```

This creates or reuses `.venv`, installs every development tool, and runs the
local deterministic release gate. GitHub's manually dispatchable **CI**
workflow is the authoritative Python 3.10–3.14 check. Live API tests remain
separate and intentionally opt-in:

```bash
./scripts/run_release_gate.sh --live
```

See the [security and reliability release gate](docs/RELEASE_GATE.md) for
manual commands, expected diagnostics, and GitHub workflow instructions.

## License

GetBible Librarian is licensed under the GNU General Public License v2.0 or later. See [LICENSE](LICENSE).
