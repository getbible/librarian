# HTTP GET service integration

Librarian is a Python library and does not start an HTTP server. The official
GetBible deployment keeps reference retrieval and full-text search behind two
independent, read-only services:

| Service | Public contract | Librarian call |
|---|---|---|
| Query | `GET https://query.getbible.net/v2/{translation}/{reference}` | `GetBible.select()` |
| Search | `GET https://search.getbible.net/v2/{translation}?q={query}` | `GetBible.search()` |

The Query service must not expose search filters or a search route. The Search
service must not expose reference lookup, legacy Query redirects, or the old
combined `/v2/search/{translation}` route. Neither service requires or exposes
a POST operation.

## Query service

Reference requests remain path-driven and return the established chapter-keyed
`select()` object without a new response envelope:

```bash
curl --get 'https://query.getbible.net/v2/kjv/James%201:1'
```

The service maps a validated request directly to Librarian:

```python
response = bible.select(reference, translation)
```

This route preserves Librarian's lightweight chapter retrieval path. It must
not download a full translation solely to answer a reference request. A
reference-only service should disable full-translation search caches and bound
its reference, book, and chapter caches for each worker.

## Search service

Search criteria are supplied through the URL query string:

```bash
curl --get 'https://search.getbible.net/v2/kjv' \
  --data-urlencode 'q=faith hope' \
  --data 'words=all' \
  --data 'match=whole_word' \
  --data 'scope=new_testament' \
  --data 'case_sensitive=false' \
  --data 'limit=25'
```

`q` is the only required query parameter. Omitted filters use `SearchBible`
defaults.

### Query parameter mapping

| URL parameter | `SearchBible` field | Accepted values | Default |
|---|---|---|---|
| `q` | Search method argument | Non-empty text | Required |
| `words` | `words` | `all`, `any`, `phrase` | `all` |
| `match` | `match` | `whole_word`, `substring` | `whole_word` |
| `case_sensitive` | `case_sensitive` | `true`, `false` | `false` |
| `scope` | `scope` | `bible`, `old_testament`, `new_testament`, `deuterocanon` | `bible` |
| `book` | `books` | Repeatable book name or number | All books |
| `books` | `books` | Comma-separated names or numbers | All books |
| `diacritics` | `diacritics` | `sensitive`, `insensitive` | `sensitive` |
| `exclude` | `exclude` | Repeatable excluded term | None |
| `proximity` | `proximity` | Integer from 0 through 100 | None |
| `sort` | `sort` | `canonical`, `relevance` | `canonical` |
| `limit` | `limit` | Public-service bounded positive integer | `100` |
| `offset` | `offset` | Public-service bounded non-negative integer | `0` |

Use repeated parameters where delimiters could be ambiguous:

```text
/v2/kjv?q=faith&book=Genesis&book=Matthew&exclude=darkness
```

The service layer should reject unknown parameters, repeated non-repeatable
parameters, invalid booleans and integers, empty filters, overlong input, and
pagination values above its public limits before calling Librarian. It should
URL-decode values exactly once and pass only supplied, validated filters:

```python
criteria = SearchBible.from_value(validated_filter_values)
rate_tier = "strict" if criteria.expensive else "normal"
with limiter.reserve(caller_identity, tier=rate_tier):
    response = bible.search(query, translation, criteria)
```

Do not pass raw query values through Python truthiness (`bool("false")` is
`True`), silently ignore unknown filters, or expose regular expressions.

The strict tier must have a lower sustained rate and burst than the normal
tier. Apply it before calling `search()`; do not discover that a request is
expensive only after loading a translation. Independently cap concurrent
Search requests and place an application deadline outside Librarian's
cooperative deadline. Recommended starting values and timeout ordering are in
[Multi-worker API operations](OPERATIONS.md).

Return `bible.search()` directly as JSON. Its `results` object retains the same
chapter-keyed Scripture structure as `select()`; `query` and `matches` are the
additive search layers.

## Separate deployment state

The two services may read the same API-compatible local mirror, but they should
use separate processes, service users, sockets, rate limits, response caches,
logs, and writable Librarian cache directories. This prevents expensive search
traffic and full-translation indexes from consuming Query capacity.

For a local mirror:

```python
bible = GetBible(repo_path="/srv/getbible/api", version="v2")
```

For the remote API, only the repository value changes:

```python
bible = GetBible(repo_path="https://api.getbible.net", version="v2")
```

The public response contracts are identical in both modes. The official
high-volume deployment should prefer an atomically updated local mirror to
remove routine upstream network dependency.

## HTTP caching and privacy

Query response caches key on the full reference URL. Search response caches
must key on the complete query string, including repeated `book` and `exclude`
parameters. Keep public response-cache lifetimes shorter than Librarian's
repository freshness interval.

The search response `query.sha` identifies the exact translation payload and
`query.cache.stale` reports last-known-good fallback. Avoid logging raw search
text by default; application and reverse-proxy access logs should retain
request identifiers, lengths, counts, status, and timing without recording the
query string.

For a shared Redis, Memcached, filesystem, or proxy response cache, wrap the
entire lookup/call/write transaction in `source_operation()` and prefix the key
with `source.cache_namespace`. Activate a completed immutable mirror using
`transition_source(revision, purge_callback)`. The transition excludes readers,
serializes the external purge, commits the generation only after purge
succeeds, and causes every worker to invalidate process-local state before it
serves the new generation. Query and Search still require separate response
cache instances even when they use the same source revision.
