# Cache validation and retention

Librarian uses separate strategies for lightweight reference retrieval and full-translation search.

## Chapter cache

`select()` requests only the required chapter. The parsed chapter is retained in memory with direct verse lookup by verse number.

After the configured interval, Librarian checks the chapter SHA endpoint. If the SHA is unchanged, only the freshness timestamp changes. If it changed or is unavailable, Librarian retrieves the chapter JSON again.

No cache-maintenance background thread is created.

## Full-translation search cache

The first search for a translation follows this sequence:

1. Acquire the in-process translation lock.
2. Acquire a cross-process file lock for the translation.
3. Read and validate an existing disk entry when present.
4. Retrieve `/v2/{translation}.sha`.
5. Download `/v2/{translation}.json` only when needed.
6. Calculate SHA-1 over the received bytes.
7. Compare it with the published SHA.
8. Validate the translation and books structure.
9. Atomically replace the disk JSON and metadata.
10. Build the immutable in-memory corpus and default postings index.

The published GetBible `.sha` value is the raw SHA-1 of the corresponding JSON bytes.

## Refresh interval

The default interval is seven days:

```python
from datetime import timedelta

from getbible import GetBible


bible = GetBible(cache_ttl=timedelta(days=7))
```

Freshness is checked lazily on the next relevant request. There is no timer and no worker wake-up cycle.

## Cache directory

Resolution order:

1. The `cache_dir` constructor argument.
2. `GETBIBLE_CACHE_DIR`.
3. `XDG_CACHE_HOME/getbible`.
4. `~/.cache/getbible`.

For a multi-worker service, configure one writable cache directory shared by all workers:

```python
bible = GetBible(cache_dir="/var/cache/getbible")
```

The cache namespace includes a hash of the repository URL or path and its API version, preventing custom repositories from colliding with official API data.

## Cross-process safety

`filelock` coordinates initial downloads and replacements. JSON and metadata are written to temporary files, flushed, and atomically moved into place. Other workers continue reading a complete previous file or the complete replacement.

Each process maintains its own in-memory corpus and indexes. The shared disk cache prevents every worker from downloading the full translation independently.

## Last-known-good behavior

When a verified disk translation exists and the source becomes temporarily unavailable, Librarian serves the cached translation and reports:

```text
query.cache.stale = true
```

The original SHA remains in the response. This makes availability and source state explicit to the API layer.

Use strict freshness when stale responses are not acceptable:

```python
bible = GetBible(strict_freshness=True)
```

In strict mode, repository failures propagate instead of serving the older translation.

Checksum mismatches never replace the last-known-good translation.

## Rotation

Each repository, API version, and translation combination keeps one current JSON payload and one metadata file. Updates replace the existing entry rather than accumulating historical full translations. Lock files contain no scripture data.
