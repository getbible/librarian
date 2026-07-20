# Usage and reference retrieval

## Client construction

```python
from datetime import timedelta

from getbible import GetBible, SearchLimits


bible = GetBible(
    repo_path="https://api.getbible.net",
    version="v2",
    cache_ttl=timedelta(days=7),
    request_timeout=(3.05, 60.0),
    request_retries=3,
    cache_dir="/var/cache/getbible",
    strict_freshness=False,
    reference_cache_limit=5000,
    books_cache_limit=64,
    chapter_cache_limit=2048,
    search_corpus_limit=4,
    translation_cache_limit=4,
    cache_ttl_jitter=0.1,
    require_checksums=True,
    search_limits=SearchLimits(),
)
```

All constructor arguments are optional. The defaults use GetBible API v2 and
the operating system's user cache directory. Checksums are required
automatically for HTTP/HTTPS repositories and optional for local repositories;
pass `require_checksums=True` for a production local mirror.

For services, construct a long-lived client rather than one client per request. The client is safe for concurrent threads, and each process receives fork-safe HTTP sessions.

The cache limits are per process. Set a limit to `0` to disable that in-memory
cache or to `None` for unbounded retention. Unbounded full translations or
search corpora are not recommended in long-running public services.

Close network sessions during orderly shutdown:

```python
bible.close()
```

Short-lived scripts may instead use `with GetBible() as bible:`.

## Select verses as a dictionary

```python
from getbible import GetBible


bible = GetBible()
selection = bible.select("Genesis 1:1-3;John 3:16", "kjv")
```

Multiple references are separated with semicolons. Verse lists and ranges are supported:

```python
selection = bible.select("John 3:16,18-21;Romans 8:1-4", "kjv")
```

The return value is grouped by translation, book number, and chapter:

```text
kjv_43_3
kjv_45_8
```

Each grouped object contains translation metadata, book and chapter metadata, the input references that contributed to the group, and an ordered `verses` list.

## Select verses as JSON

```python
encoded = bible.scripture("Psalm 23:1-6", "kjv")
```

`scripture()` calls `select()` and encodes the result with Unicode characters preserved.

## Validate input

```python
reference_is_valid = bible.valid_reference("1 John 3:16", "kjv")
translation_is_valid = bible.valid_translation("kjv")
```

`valid_reference()` verifies that the book alias and reference syntax can be resolved. The final chapter and verse existence check occurs during `select()`.

`valid_translation()` checks the configured repository's `books.json` resource and caches the result for the configured cache interval.

## Resolve references directly

```python
from getbible import GetBibleReference


references = GetBibleReference()
resolved = references.ref("First John 3:16,19-21", "kjv")
print(resolved.book)
print(resolved.chapter)
print(resolved.verses)
```

Reference cache keys include the translation code. Frequently used entries are retained with a bounded least-recently-used policy.

## Resolve book numbers directly

```python
from getbible import GetBibleBookNumber


books = GetBibleBookNumber()
number = books.number("1 John", "kjv")
print(number)
```

The book resolver uses bundled Unicode-normalized alias tries. It tries the requested translation, KJV aliases, and then configured fallback translations.

## Local API-compatible repository

The same client can read API v2-compatible files from disk. A string path or a `pathlib.Path` can be used:

```python
from pathlib import Path

from getbible import GetBible


bible = GetBible(repo_path=Path("/srv/getbible-data"), version="v2")
selection = bible.select("Genesis 1:1", "kjv")
```

Switching back to the remote API changes only `repo_path`:

```python
bible = GetBible(repo_path="https://api.getbible.net", version="v2")
```

Local paths and HTTP(S) URLs use the same API-compatible layout and return the same scripture and search JSON contracts. Deterministic tests serve the local fixture repository over HTTP and compare both modes directly.

Expected paths include:

```text
/srv/getbible-data/v2/kjv/books.json
/srv/getbible-data/v2/kjv/1/1.json
/srv/getbible-data/v2/kjv.json
/srv/getbible-data/v2/kjv.sha
```

The `.sha` resource is optional for local fixtures and required for remote
repositories. Production local mirrors should opt into the same enforcement.

## Errors

- Invalid reference syntax raises `ValueError`.
- Missing translations and chapters preserve the existing `FileNotFoundError` contract.
- Repository transport failures raise `RepositoryError`.
- Invalid JSON raises `RepositoryResponseError`.
- Checksum or structural failures raise `CacheIntegrityError`.
- Invalid search criteria raise `SearchValidationError`.
