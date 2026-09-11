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

For a multi-process application, configure one writable cache directory shared by all processes:

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

The original SHA remains in the response. This makes availability and source state explicit to the application.

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

## Local repositories

When `repo_path` is a directory rather than a URL, the full translation is
validated and held in memory exactly as for a remote repository, but no copy
is written under the cache directory: the source file already sits on the
same disk, so a duplicate would buy nothing. The metadata file still records
the validated SHA, the books-index checksum and the freshness timestamp, so
processes share freshness state and a changed source is noticed at the next
freshness check. A source file whose bytes no longer match the recorded SHA
is simply re-read and re-validated.

Remote repositories keep the content-addressed on-disk copy, which is what
makes last-known-good fallback possible when the source is unreachable.

## Rotation

Each translation metadata file points to one current content-addressed payload.
Older unreferenced objects may be removed during controlled cache maintenance
after all workers have observed the new generation. Lock and barrier files
contain no scripture data.

Use `GetBible.cache_info()` to observe current sizes, configured limits,
evictions, source checks, downloads, stale fallbacks, loaded SHA values, and
built index variants without exposing Scripture payloads.


## Resident cache controls (2.1)

A freshness TTL is an interval before the next source verification. It is not
an instruction to discard immutable data. After the interval elapses, the next
request rechecks the source and retains the same corpus and built indexes when
the SHA is unchanged. Requests do not extend the interval. Changed source
revisions can be published immediately with `transition_source(revision)`;
there is no need to wait for TTL expiration.

```python
from datetime import timedelta
from getbible import GetBible

bible = GetBible(
    cache_ttl=timedelta(days=30),
    cache_ttl_jitter=0,
    chapter_cache_limit=100_000,
    chapter_cache_bytes=512 * 1024**2,
    search_corpus_limit=100,
    translation_cache_limit=100,
    translation_cache_bytes=512 * 1024**2,
    shared_corpus_limit=100,
    shared_corpus_bytes=1024**3,
)
```

These example limits illustrate the API; they are not measured requirements
for a complete translation collection. Set count and byte bounds appropriate
to the application. The library retains its existing conservative defaults
unless explicitly configured. A byte or count limit takes precedence over
residency: least-recently-used entries can be evicted before their TTL when a
bound is reached. A single oversized request may execute without retaining its
result in a cache. No new background thread, eager translation download, or
periodic rebuild is introduced by construction.

| Parameter | Scope | `None` | `0` |
| --- | --- | --- | --- |
| `chapter_cache_limit` | Chapters retained by this client | No count limit | No retention |
| `chapter_cache_bytes` | Estimated bytes in those chapters | No byte limit | No retention |
| `translation_cache_limit` | Full validated snapshots in this client | No count limit | No retention |
| `translation_cache_bytes` | Estimated bytes in those snapshots | No byte limit | No retention |
| `search_corpus_limit` | This client's retained corpus references | No count limit | No client retention |
| `shared_corpus_limit` | Process-wide strong corpus registry | Constructor leaves registry unchanged | No registry retention |
| `shared_corpus_bytes` | Process-wide registry and this client's corpus references | No byte limit when explicitly configured | No retention |

For shared settings, configure one policy for the process. A later explicit
shared-registry configuration applies to the same process-wide registry.
Changing the registry does not forcibly invalidate immutable objects already
borrowed by another client or active request. A weak lookup table allows those
objects to be reused without parsing and indexing the same SHA again, while
not preventing their release once all borrowers let go. This weak table is
bounded by the number of objects that are actually alive, not by historical
request keys. In-flight data and other clients' references can exceed the
registry's retained-byte limit; these are not operating-system memory limits.

Reconfiguration validates every argument before applying any changes. Omitted
arguments remain unchanged, and existing objects and freshness timestamps are
preserved when capacity grows:

```python
state = bible.configure_cache(
    cache_ttl=timedelta(days=7),
    cache_ttl_jitter=0,
    chapter_cache_limit=200_000,
    shared_corpus_limit=150,
)
```

`configure_cache(shared_corpus_limit=None)` is invalid: unlike the constructor's
"leave unchanged" default, a registry resize requires a non-negative integer.
To leave the setting unchanged, omit it. Set all retention bounds deliberately
rather than removing both count and byte limits from a client cache.

## Explicit query and search lifecycle

```python
# The normal lazy path fetches only the requested chapter:
bible.select("John 3:16", "kjv")

# Optional targeted prewarming uses that same chapter path:
bible.warm_query("kjv", references=["John 3:16", "Genesis 1:1"])

# Explicitly warm all query chapters from a validated full snapshot.
# This does not build a search corpus or index:
query_state = bible.warm_query("kjv")

# Existing search warm-up builds the selected analysed search view:
search_state = bible.warm_translation("kjv")

# Drop resident views, keeping cached source bytes and source repository files:
bible.drop_translation("kjv")

# Force source verification and rebuild either or both views:
bible.reload_translation("kjv", target="both")
```

`warm_query` returns both the amount loaded and the amount still retained.
They may differ when the selected count/byte capacity cannot hold all chapters.
`references` must be a sequence of strings, not a comma-separated string.
`reload_translation` accepts `search`, `query`, or `both`, plus optional query
references. Source bytes are verified before the current views are discarded;
configured last-known-good fallback is reported as stale. Existing repository
failure and strict-freshness rules apply.

Explicit drop/reload/reconfiguration excludes active source readers during its
administrative operation. Calls are intended for administration, not for every
request. They affect this client's resident views and the process registry;
independent clients or worker processes must each receive their own operation.
`transition_source` remains the shared revision/invalidation mechanism.

`drop_translation(code, disk=True)` additionally deletes that translation's
Librarian-owned metadata and referenced downloaded cache object. It never
deletes repository source files or another translation's cache objects. It does
not revoke the source generation or cancel an immutable response already held
by application code.

## Memory measurements

`cache_info()` returns JSON-safe metadata, including:

- `ttl_seconds` and `freshness_policy`;
- `query_translations[code]`: retained chapter count, estimated bytes, and how
  many chapters are due for lazy revalidation;
- `search_corpora.translations[code]`: SHA, verification time, stale state,
  verse count, built index policies, and estimated bytes;
- `translation_cache.translations[code]`: snapshot size estimates and state;
- `translation_cache.source_generation` and the existing `source` manifest;
- `shared_registry`: retained entries/bytes, bounds, hits, misses, evictions and
  active corpus-build locks.

The measurement label is `estimated_python_objects_not_rss`. These values count
reachable Python data structures and native array buffers, not interpreter
heaps, memory fragmentation, process RSS, or peak temporary allocations. Shared
objects can appear in more than one category or worker estimate, so those
values must not be summed and presented as actual physical memory consumption.
Byte sizing is calculated during insertion/index construction and reused for
warm requests; it does not walk an entire translation for every query or chart.
An active request, a cold build, or old/new generations overlapping in application
code require additional headroom beyond retained cache limits.
