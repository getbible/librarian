# Multi-worker API operations

Librarian is designed to be held as a long-lived application dependency in
each API worker. Deploy the reference Query and full-text Search APIs as
independent services so search CPU and memory cannot consume Query capacity.

## Client lifetime

Create one client during application initialization or once per worker. Do not construct a new client for every HTTP request.

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

The example functions are framework-neutral and can be called by Flask, Django,
FastAPI, or another WSGI/ASGI endpoint. They illustrate Librarian calls only;
the official deployment places them in separate processes and writable cache
directories.

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
index is known to be common:

```python
bible.warm_translation("kjv", case_sensitive=True, diacritics="insensitive")
```

## Bounded memory

Every growing process-local cache is bounded by default:

| Cache | Constructor argument | Default entries |
|---|---|---:|
| Parsed references | `reference_cache_limit` | 5,000 |
| Translation book lists | `books_cache_limit` | 64 |
| Retrieved chapters | `chapter_cache_limit` | 2,048 |
| Full search corpora and indexes | `search_corpus_limit` | 4 |
| Validated translation snapshots | `translation_cache_limit` | 4 |

These limits apply to each worker process, not to the whole deployment. Size
worker memory for the largest translations and index variants actually served.
Use `0` to disable retention or `None` for an unbounded cache. Avoid `None` for
full translations and corpora in a public multi-translation service.

For a Query-only process, set `search_corpus_limit=0` and
`translation_cache_limit=0`. For a Search-only process, set
`reference_cache_limit=0` and `chapter_cache_limit=0`, then choose small corpus
and translation limits based on measured worker RSS. Both services can read the
same local API mirror but should never share a writable cache directory.

## Pagination limits

The library restricts a page to 1,000 matches. The API layer may impose a smaller public maximum. Exact totals are reported independently of the returned page.

## Search tiers and outer deadlines

Parse `SearchBible` before entering a rate-limiter reservation. Its
`expensive` property is deliberately corpus-independent:

```python
criteria = SearchBible.from_value(filters)
tier = "strict" if criteria.expensive else "normal"
with limiter.reserve(identity, tier=tier):
    response = bible.search(query, translation, criteria)
```

Use independent counters for the two tiers. A production starting point is 60
normal searches per minute with a burst of 10, and 12 strict searches per
minute with a burst of 3, per authenticated identity and per source IP. Tune
from measured capacity; never combine the strict and normal burst pools.

The default cooperative Librarian deadline is 5 seconds. The application
server should use a 7-second request deadline and the reverse proxy a 10-second
upstream deadline, leaving time to translate a typed failure into a clean HTTP
response. Repository connect/read timeouts govern source refresh separately.
Do not rely on a proxy timeout to stop Python work: it disconnects the caller
but does not itself cancel matching.

## Timeouts and retries

Defaults:

- Connect timeout: 3.05 seconds.
- Read timeout: 60 seconds.
- Retries: 3 for GET requests.
- Retry statuses: 429, 500, 502, 503, and 504.

Override these through `GetBible()` when the hosting environment requires different limits.

## systemd cgroup limits

Maintained baseline drop-ins are provided for independent Query and Search
units:

```bash
sudo install -D -m 0644 \
  deploy/systemd/getbible-query.service.d/limits.conf \
  /etc/systemd/system/getbible-query.service.d/limits.conf
sudo install -D -m 0644 \
  deploy/systemd/getbible-search.service.d/limits.conf \
  /etc/systemd/system/getbible-search.service.d/limits.conf
sudo systemctl daemon-reload
sudo systemctl restart getbible-query.service getbible-search.service
sudo systemctl show getbible-query.service getbible-search.service \
  -p MemoryHigh -p MemoryMax -p MemorySwapMax -p CPUQuotaPerSecUSec -p TasksMax
```

The Query baseline is 512 MiB/200% CPU/64 tasks. Search is isolated at 3
GiB/400% CPU/128 tasks. Both disable swap for the unit and stop on an OOM event.
Treat these as tested starting limits: lower corpus counts before raising
`MemoryMax`, and validate the chosen values under a full-translation load test.

## Monitoring

The API layer should record:

- request duration by reference and search endpoint;
- translation, criteria mode, and page size;
- cache `stale` state;
- repository and checksum failures;
- worker memory after each newly loaded translation/index mode;
- search totals and response sizes;
- rate limiting and rejected criteria.

`cache_info()` provides JSON-safe sizes, limits, hit/miss/eviction counters,
loaded translation SHA values, stale flags, and currently built index variants.
It deliberately excludes verse text, source paths, and search terms:

```python
state = bible.cache_info()
metrics.gauge("librarian.search_corpora", state["search_corpora"]["size"])
metrics.counter("librarian.search_evictions", state["search_corpora"]["evictions"])
```

Read these counters periodically or at worker shutdown. Do not call
`cache_info()` on every public request solely for logging.

## Shutdown

Call `bible.close()` from the worker/application shutdown hook after request
threads have stopped. It closes every HTTP session created by that process.
Short-lived scripts can use `GetBible` as a context manager.

Do not log complete private caller context. In particular, keep raw search text
out of application and reverse-proxy logs by default; record request IDs,
lengths, counts, status, and timing instead.

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
