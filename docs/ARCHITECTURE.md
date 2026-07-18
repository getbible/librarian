# Architecture

## Public facade

`getbible.GetBible` is the stable public entry point.

- `select()` and `scripture()` use chapter retrieval.
- `search()` and `search_json()` use a full-translation corpus.
- `valid_reference()` and `valid_translation()` expose validation helpers.
- `warm_translation()` performs explicit corpus/index warm-up without a fake query.
- `cache_info()` and `close()` support service monitoring and orderly shutdown.

## Modules

| Module | Responsibility |
|---|---|
| `getbible.py` | Public facade, grouped scripture output, and cache coordination |
| `repository_client.py` | Remote/local resource access, retries, timeouts, and fork-safe connection pooling |
| `translation_cache.py` | SHA validation, disk persistence, atomic replacement, and stale fallback |
| `search.py` | Criteria validation, corpus construction, postings indexes, matching, scoring, and pagination |
| `getbible_reference.py` | Reference parsing and translation-aware LRU caching |
| `getbible_book_number.py` | Translation alias selection and fallback |
| `getbible_reference_trie.py` | Unicode-normalized book alias prefix tree |

## Reference request flow

```text
reference string
  -> validate and parse
  -> resolve book alias through trie
  -> read fresh chapter cache or API chapter
  -> direct verse-number lookup
  -> grouped scripture objects
```

This path never downloads a full translation solely to serve a reference.

## Search request flow

```text
query and criteria
  -> validate translation and criteria
  -> load verified translation snapshot
  -> reuse/build normalized postings index
  -> resolve testament and book scope
  -> match, score, and calculate exact total
  -> paginate
  -> grouped scripture objects plus query/match metadata
```

## Search index

The corpus contains canonical immutable `VerseRecord` objects. Each normalization mode creates a lazy `SearchIndex` containing:

- one normalized text string per verse;
- a token-to-verse postings map stored in compact unsigned-integer arrays;
- document frequencies for fast exact totals.

The default case-insensitive, diacritic-sensitive index is built by the first default search. Alternative case or diacritic modes build their own index only when used.

Exact whole-word queries use postings rather than scanning every verse. Partial-word queries scan the much smaller token vocabulary. Phrase and proximity searches use postings to reduce candidate verses before verification.

## Concurrency model

- Normal search reads do not take a translation-wide lock.
- One thread builds a missing corpus or normalization index; other threads reuse the result.
- One process downloads or replaces a disk translation at a time.
- HTTP sessions are thread-local and carry the process ID, so a pre-fork worker creates a new session after the fork.
- Cache and lock registries use bounded or reference-counted retention so translation churn does not grow worker memory indefinitely.
- Unchanged source SHAs update corpus freshness without replacing immutable verse records or indexes.
- No per-instance maintenance thread exists.

## Compatibility boundary

The grouped chapter object is the compatibility boundary. Search wraps this structure under `results` and adds `query` and `matches`. Existing verse dictionaries are returned without modifying their API fields or text.

## HTTP deployment boundary

Librarian supplies both capabilities, but the official HTTP layer deliberately
separates them. Query maps `GET /v2/{translation}/{reference}` to `select()`;
Search maps `GET /v2/{translation}?q=...` to `search()`. They run with separate
process and cache budgets. The earlier combined `/v2/search/{translation}`
shape is not part of the supported deployment contract.
