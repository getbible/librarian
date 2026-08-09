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
| `source_generation.py` | Atomic mirror generations, cross-worker barriers, response-cache namespaces, and invalidation |
| `search/analysis.py` | Writing-system classification and the tokenization rules each family needs |
| `search/index.py` | Positional postings, n-gram chains, and trigram candidate generation |
| `search/corpus.py` | Verse records, lazily built indexes, and the process-wide corpus registry |
| `search/criteria.py` | `SearchBible` validation and serialization |
| `search/limits.py` | Per-request work reservation and cooperative deadlines |
| `search/engine.py` | Query units, matching, scoring, and pagination |
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
  -> validate criteria and corpus-independent limits
  -> load verified translation snapshot
  -> acquire shared corpus (registry: repository + translation + SHA)
  -> reserve the floor cost, then reuse/build the analysed index
  -> analyse the query into units, one per word or per continuous run
  -> resolve each unit through positional postings
  -> combine by word mode, exclude, apply proximity
  -> scope to testament and books, score, calculate exact total
  -> paginate
  -> grouped scripture objects plus query/match metadata
```

## Analysis

A verse and a query are split into maximal runs of one writing system, and each
run is analysed by that system's rules. Classification uses Unicode Script
Extensions and line-breaking properties rather than a range table or the
translation's declared language tag, so a translation added to the API later is
handled without a code change.

Alphabetic and abjad runs fold combining marks and precomposed letters; Brahmic
and continuous runs keep theirs, because there the marks carry vowels. Abjad
runs additionally index the stem behind an attached closed-class particle.

Because the corpus and the query pass through the same analyser, the caller
never selects a matching strategy. That decision does not exist in the public
API.

## Search index

The corpus holds canonical immutable `VerseRecord` objects. Each analysis policy
— a `(case_sensitive, fold_diacritics)` pair — creates one lazy `SearchIndex`:

- the prepared text of every verse;
- a term-to-`(verse, position)` postings map in compact unsigned-integer arrays;
- document frequencies for exact totals;
- a script census describing what the translation contains;
- a trigram table over the term dictionary, built only if a substring search
  arrives.

Space-delimited scripts index words. Continuous scripts index overlapping
character n-grams, and a multi-character run is verified by requiring its
bigrams at consecutive positions — exact, and settled by positions alone, so no
verse text is rescanned. Substring queries generate candidate terms from the
trigram table instead of comparing every vocabulary entry to every query term.

Work is estimated from postings lengths. The 1.x estimator walked the whole
vocabulary once per term and cost more than the search it guarded.

## Corpus sharing and index construction

Corpora live in a process-wide registry keyed by repository, translation and
source SHA. Separate `GetBible` objects reach the same parsed verses and the
same analysed index, so a service pays that cost once per translation version.
Keying on the SHA means an upstream change produces a new entry rather than
silently reusing stale verses.

An index build is bounded by `SearchLimits.index_build_seconds`, not by the
requesting call's `deadline_seconds`. A build serves every later request;
abandoning one part way cached nothing and sent the next request down the same
path. Concurrent first requests wait on a single build. A request whose work
budget cannot cover the corpus is still refused before any build starts.

## Concurrency model

- Normal search reads do not take a translation-wide lock.
- One thread builds a missing corpus or analysed index; other threads wait and reuse the result.
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

The source-generation layer is independent of per-translation freshness. A
deployment activates a completed immutable mirror revision with
`transition_source()`. Requests and external response-cache transactions use
`source_operation()` so a purge and generation change cannot race a read. The
stable repository namespace plus monotonic generation prevents old response
keys from becoming valid again after a transition.
