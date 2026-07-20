# Cache validation and retention

Librarian uses separate strategies for lightweight reference retrieval and full-translation search.

## Chapter cache

`select()` requests only the required chapter. The parsed chapter is retained in memory with direct verse lookup by verse number.

Before retaining a chapter, Librarian retrieves and validates its SHA endpoint,
downloads the JSON, validates the exact checksum, and validates every required
chapter and verse field. After the configured interval, an unchanged SHA only
updates freshness. Remote production repositories must publish the checksum;
checksum-free local fixtures remain supported.

No cache-maintenance background thread is created.

## Full-translation search cache

The first search for a translation follows this sequence:

1. Acquire the in-process translation lock.
2. Acquire a cross-process file lock for the translation.
3. Read and validate an existing disk entry when present.
4. Retrieve `/v2/{translation}.sha`.
5. Retrieve and independently validate `/v2/{translation}/books.json`.
6. Download `/v2/{translation}.json` only when needed.
7. Calculate SHA-1 over the received bytes and compare it with the published SHA.
8. Validate every book, chapter, verse, numeric range, unique identifier, text
   ceiling, and the exact books-index correspondence.
9. Write the validated JSON as an immutable `objects/{sha}.json` payload.
10. Atomically commit versioned metadata that points at that content-addressed
    payload.
11. Build the immutable in-memory corpus and default postings index.

When the source SHA is unchanged, Librarian updates only freshness state and
retains the existing corpus and every already-built index. It does not reread
and decode the full disk JSON or rebuild postings merely because the freshness
interval elapsed.

The published GetBible `.sha` value is the raw SHA-1 of the corresponding JSON bytes. HTTP/HTTPS repositories require it by default. Set `require_checksums=False` only for a controlled compatibility source; set `require_checksums=True` to enforce the production rule for a local mirror.

## Refresh interval

The default interval is seven days:

```python
from datetime import timedelta

from getbible import GetBible


bible = GetBible(cache_ttl=timedelta(days=7))
```

Freshness is checked lazily on the next relevant request. There is no timer and no worker wake-up cycle.

By default, each process deterministically shortens individual translation
refresh intervals by up to 10 percent. This `cache_ttl_jitter` spreads source
checks across many workers while never serving an entry beyond the configured
TTL. Use `cache_ttl_jitter=0` for exact intervals.

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

`filelock` coordinates initial downloads and commits. Immutable payloads and
metadata are written to temporary files, flushed, atomically moved into place,
and followed by a directory `fsync`. Metadata is the commit point. A process
crash can leave an unreferenced immutable object, but cannot make a partially
validated object current. Metadata includes a validation-version marker so a
future validator upgrade forces complete revalidation.

Each process maintains its own in-memory corpus and indexes. The shared disk cache prevents every worker from downloading the full translation independently.

Process-local caches use bounded least-recently-used retention. The defaults
retain four translation snapshots and four search corpora per worker; chapter,
book-list, and parsed-reference caches have separate limits. Eviction removes a
lookup entry but never mutates an immutable corpus already borrowed by an active
request.

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

Checksum, nested validation, and books-index mismatches never replace the
last-known-good translation. Unless strict freshness is enabled, a validated
last-known-good corpus remains available and is marked stale when a newly
published upstream payload fails integrity validation.

## Source generations

The repository URL/path plus API version produces a stable namespace. A
versioned `source-generation.json` manifest records the active immutable mirror
revision. `transition_source()` takes the cross-process writer barrier, runs the
configured response-cache purge callback exactly once, commits the manifest,
and invalidates worker-local books, chapters, full translations, indexes, and
negative translation entries. A purge failure leaves the old generation
committed.

Use `source_operation()` to keep the generation stable while an application
performs an external response-cache lookup, Librarian call, and response-cache
write:

```python
with bible.source_operation() as source:
    key = f"{source.cache_namespace}:{canonical_request_key}"
    response = response_cache.get(key)
    if response is None:
        response = bible.search(query, translation, criteria)
        response_cache.set(key, response)
```

The reader/transition barrier spans threads and Linux worker processes. A
worker that observes a generation committed by another worker invalidates its
process-local caches before serving that generation. Translation metadata also
records the source generation; an older disk snapshot becomes immediately due
for source revalidation, even when its ordinary cache TTL has not elapsed.

## Rotation

Each translation metadata file points to one current content-addressed payload.
Older unreferenced objects may be removed during controlled cache maintenance
after all workers have observed the new generation. Lock and barrier files
contain no scripture data.

Use `GetBible.cache_info()` to observe current sizes, configured limits,
evictions, source checks, downloads, stale fallbacks, loaded SHA values, and
built index variants without exposing Scripture payloads.
