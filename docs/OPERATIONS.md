# Multi-worker API operations

Librarian is designed to be held as a long-lived application dependency in each API worker.

## Client lifetime

Create one client during application initialization or once per worker. Do not construct a new client for every HTTP request.

```python
from getbible import GetBible


bible = GetBible(cache_dir="/var/cache/getbible")


def execute_scripture_query(reference: str, translation: str) -> dict:
    return bible.select(reference, translation)


def execute_search_query(query: str, translation: str, criteria: dict) -> dict:
    return bible.search(query, translation, criteria)
```

The example functions are framework-neutral and can be called by Flask, Django, FastAPI, or another WSGI/ASGI endpoint.

## Worker processes

Each worker has its own in-memory chapter cache, corpus objects, and postings indexes. Workers share the disk translation cache through process locks and atomic replacement.

Configure the cache directory so every worker identity can read and write it. Do not place it inside an ephemeral per-request directory.

## Pre-fork servers

Librarian detects process changes and does not reuse an HTTP session created by the parent process. This makes the client safe when an application server preloads the module before forking workers.

To share as much read-only memory as the operating system permits, a deployment may warm its most-used translation and default index before forking:

```python
from getbible import GetBible, SearchCriteria


bible = GetBible(cache_dir="/var/cache/getbible")
bible.search("the", "kjv", SearchCriteria(limit=1))
```

Whether preloading is beneficial depends on the server, worker lifecycle, and available memory. Benchmark both preloaded and per-worker warm-up configurations.

## Threads

Repository sessions are thread-local. Normal cache reads are concurrent. Missing corpus and index construction is coordinated so only one thread performs the expensive work in a process.

## Warm-up

The first search for a translation includes disk or network loading, JSON parsing, corpus construction, and index construction. Warm the expected translation before marking a newly started worker ready when startup latency matters.

Do not warm every case and diacritic variant unless production traffic requires them; each variant consumes additional memory.

## Pagination limits

The library restricts a page to 1,000 matches. The API layer may impose a smaller public maximum. Exact totals are reported independently of the returned page.

## Timeouts and retries

Defaults:

- Connect timeout: 3.05 seconds.
- Read timeout: 60 seconds.
- Retries: 3 for GET requests.
- Retry statuses: 429, 500, 502, 503, and 504.

Override these through `GetBible()` when the hosting environment requires different limits.

## Monitoring

The API layer should record:

- request duration by reference and search endpoint;
- translation, criteria mode, and page size;
- cache `stale` state;
- repository and checksum failures;
- worker memory after each newly loaded translation/index mode;
- search totals and response sizes;
- rate limiting and rejected criteria.

Do not log complete private caller context. Scripture queries themselves are generally safe, but operational logging policy remains the responsibility of the API service.

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
