# Multi-process operations

Librarian is designed to be held as a long-lived dependency in each process
of an application. Retrieval and search are independent capabilities; an
application that serves both under load often runs them in separate processes
so search CPU and memory cannot starve retrieval, and the library supports
either arrangement.

## Client lifetime

Create one client during application initialization or once per worker. Do not construct a new client for every call.

```python
from getbible import GetBible, SearchLimits


bible = GetBible(
    cache_dir="/var/cache/getbible",
    require_checksums=True,
    search_limits=SearchLimits(deadline_seconds=5.0),
)


def execute_scripture_query(reference: str, translation: str) -> dict:
    return bible.select(reference, translation)


def execute_search_query(query: str, translation: str, criteria: dict) -> dict:
    return bible.search(query, translation, criteria)
```

The example functions are framework-neutral. They illustrate Librarian calls
only; what surrounds them belongs to the application.

## Worker processes

Each worker has its own in-memory chapter cache, corpus objects, and postings indexes. Workers share the disk translation cache through process locks and atomic replacement.

Configure the cache directory so every worker identity can read and write it. Do not place it inside an ephemeral per-request directory.

## Pre-fork servers

Librarian detects process changes and does not reuse an HTTP session created by the parent process. This makes the client safe when an application server preloads the module before forking workers.

To share as much read-only memory as the operating system permits, a deployment may warm its most-used translation and default index before forking:

```python
from getbible import GetBible


bible = GetBible(cache_dir="/var/cache/getbible")
bible.warm_translation("kjv")
```

Whether preloading is beneficial depends on the server, worker lifecycle, and available memory. Benchmark both preloaded and per-worker warm-up configurations.

## Threads

Repository sessions are thread-local. Normal cache reads are concurrent. Missing corpus and index construction is coordinated so only one thread performs the expensive work in a process.

## Warm-up

The first search for a translation includes disk or network loading, JSON parsing, corpus construction, and index construction. Warm the expected translation before marking a newly started worker ready when startup latency matters.

Do not warm every case and diacritic variant unless production traffic requires them; each variant consumes additional memory.

`warm_translation()` accepts `case_sensitive` and `diacritics` when a non-default
index is known to be common. It returns an `analysis` block reporting how the
translation was read, which is worth recording once per deployment:

```python
bible.warm_translation("kjv", case_sensitive=True, diacritics="exact")
```

## Shared corpora

Parsed translations and their analysed indexes live in a registry shared by
every `GetBible` in the process, keyed by repository, translation and source
SHA. A service that constructs a client per request, or holds several clients
for different configurations, pays the parse-and-analyse cost once per
translation version rather than once per object.

Keying on the SHA is what makes this safe: when a translation changes upstream,
the new SHA produces a new entry instead of silently reusing stale verses. The
superseded entry is evicted by ordinary LRU pressure.

Sharing is per process. Pre-fork workers each hold their own registry unless the
parent warmed the translation before forking, in which case the pages are shared
copy-on-write — see [Pre-fork servers](#pre-fork-servers).

## Index build window

Index construction is bounded by `SearchLimits.index_build_seconds` (120 seconds
by default), which is deliberately separate from the per-request
`deadline_seconds`.

A build serves every later request, so it must not be abandoned because one
caller's request clock ran out. Under 1.x a build charged to a request deadline
could time out, cache nothing, and leave the next request repeating the same
work and failing the same way — a stall the service could not recover from on
its own. Concurrent first requests now wait on a single build.

Raise `index_build_seconds` only if a very large translation genuinely needs
longer on your hardware; warming before traffic is the better answer.

A request whose work budget cannot cover the corpus is still refused before any
index build starts.

## Bounded memory

Every growing process-local cache is bounded by default:

| Cache | Constructor argument | Default entries |
|---|---|---:|
| Parsed references | `reference_cache_limit` | 5,000 |
| Translation book lists | `books_cache_limit` | 64 |
| Retrieved chapters | `chapter_cache_limit` | 2,048 |
| Full search corpora and indexes | `search_corpus_limit` | 4 |
| Validated translation snapshots | `translation_cache_limit` | 4 |

These limits apply to each process, not to the whole application. Size
process memory for the largest translations and index variants actually used.
Use `0` to disable retention or `None` for an unbounded cache. Avoid `None` for
full translations and corpora when many translations are in play.

For a retrieval-only process, set `search_corpus_limit=0` and
`translation_cache_limit=0`. For a search-only process, set
`reference_cache_limit=0` and `chapter_cache_limit=0`, then choose small corpus
and translation limits based on measured RSS. Processes can read the same
repository but should never share a writable cache directory.

## Pagination limits

The library restricts a page to 1,000 matches. An application may impose a smaller maximum. Exact totals are reported independently of the returned page.

## Deadlines

`SearchBible.expensive` is deliberately corpus-independent, so an application
can classify a search before it runs:

```python
criteria = SearchBible.from_value(filters)
if criteria.expensive:
    ...  # budget it however the application sees fit
response = bible.search(query, translation, criteria)
```

The default cooperative Librarian deadline is 5 seconds. An application that
wraps a call in a timeout of its own should set that timeout above the
Librarian deadline, leaving time to translate a typed failure into whatever it
reports to its callers. Repository connect/read timeouts govern source refresh
separately. A timeout imposed from outside the process does not stop Python
work: it abandons the caller but does not itself cancel matching.

## Timeouts and retries

Defaults:

- Connect timeout: 3.05 seconds.
- Read timeout: 60 seconds.
- Retries: 3 for GET requests.
- Retry statuses: 429, 500, 502, 503, and 504.

Override these through `GetBible()` when the hosting environment requires different limits.

## Monitoring

An application should record:

- call duration for retrieval and for search;
- translation, criteria mode, and page size;
- cache `stale` state;
- repository and checksum failures;
- process memory after each newly loaded translation/index mode;
- search totals and response sizes;
- rejected criteria.

`cache_info()` provides JSON-safe sizes, limits, hit/miss/eviction counters,
loaded translation SHA values, stale flags, and currently built index variants.
It deliberately excludes verse text, source paths, and search terms:

```python
state = bible.cache_info()
metrics.gauge("librarian.search_corpora", state["search_corpora"]["size"])
metrics.counter("librarian.search_evictions", state["search_corpora"]["evictions"])
```

Read these counters periodically or at shutdown. Do not call `cache_info()`
on every call solely for logging.

## Shutdown

Call `bible.close()` from the application's shutdown hook after calling
threads have stopped. It closes every HTTP session created by that process.
Short-lived scripts can use `GetBible` as a context manager.

`cache_info()` never contains verse text or search terms, so it can be logged
freely; what an application logs about its own callers is its own decision.

## Benchmarking

```bash
python benchmarks/search_benchmark.py \
  --translation kjv \
  --query "faith hope" \
  --iterations 10000 \
  --workers 1 \
  --cache-dir /var/cache/getbible
```

The benchmark reports initial warm-up time, exact match total, average warm latency, and queries per second. Use process-level load testing against the actual API service to validate worker count, network stack, serialization, and response compression.
