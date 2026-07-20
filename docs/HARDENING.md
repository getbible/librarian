# Hardening and request budgets

`GetBible` now applies a fail-closed layer before the existing retrieval and search implementation. Existing result dictionaries and JSON output remain unchanged; only malformed, excessive, or unsafe requests are rejected earlier with typed exceptions.

## Default request limits

```python
from getbible import GetBible, RequestLimits, SearchLimits

bible = GetBible(
    request_limits=RequestLimits(
        max_input_length=1024,
        max_references=8,
        max_verses_per_reference=200,
        max_total_verses=200,
    ),
    search_limits=SearchLimits(
        max_work_units=50_000_000,
        max_response_bytes=4 * 1024 * 1024,
        max_query_length=500,
        max_query_terms=64,
        min_substring_length=3,
        max_books=83,
        max_exclusions=32,
        max_exclusion_terms=64,
        max_offset=10_000,
        max_limit=1_000,
        deadline_seconds=5.0,
    ),
    request_timeout=(3.05, 30.0),
    request_retries=3,
    max_response_bytes=128 * 1024 * 1024,
)
```

The parser has an independent hard ceiling of 200 verses per reference and validates the range size before constructing it. A service may configure stricter values. Public chat and HTTP layers should normally do so.

Search work is estimated deterministically from the corpus index, requested
criteria, filter breadth, sorting mode, and response page before matching is
allowed to continue. Execution performs cooperative deadline checks while
building an index, scanning postings, testing phrases, and evaluating
proximity. The response is serialized into the configured byte budget before
it is returned.

Substring terms must contain at least three characters by default. This stops
one-character vocabulary scans before the translation corpus is loaded.
`SearchBible.expensive` classifies substring, phrase, any-word, proximity,
relevance, exclusion, insensitive-diacritic, deep-offset, and large-page
criteria before execution so the HTTP layer can apply its strict rate tier.

Legacy open forms such as `John 1:2-` and `John 1:-5` retain their established single-verse meaning. Reversed ranges, zero, malformed punctuation, and ranges above the configured ceiling are rejected.

## Typed failures

- `ReferenceValidationError`: malformed or unresolved reference; remains a `ValueError`.
- `RequestLimitError`: input exceeded a finite work budget; remains a `ValueError`.
- `SearchLimitError`: deterministic work, filter, pagination, or response budget exceeded; it is both a `SearchValidationError` and `RequestLimitError`.
- `SearchDeadlineExceeded`: cooperative search deadline elapsed; it is also a `TimeoutError`.
- `TranslationNotFoundError`: missing translation; remains a `FileNotFoundError`.
- `RepositoryTimeoutError`: connect or read deadline exceeded.
- `RepositoryResponseTooLarge`: declared or streamed content exceeded the byte cap.
- `RepositoryError`: other repository access failures.

Applications should map these classes to stable public messages and log unexpected exceptions with a correlation identifier. They should never echo raw exception strings to untrusted users.

## Translation validation

Positive translation data uses the existing bounded book cache. Missing translations use a separate bounded TTL/LRU cache so repeated invalid identifiers do not repeatedly reach the repository. Search and warm-up perform this check before an abbreviation-specific translation payload path or lock can be created. Translation codes still require a complete match of the established identifier grammar.

Remote repositories require published full-translation and chapter SHA-1
checksums by default. Local repositories permit checksum-free fixtures unless
`require_checksums=True` is selected. Complete corpus validation enforces
bounded book/chapter/verse counts, numeric ranges, unique identifiers, required
text fields, chapter consistency, and equality with the independent
`books.json` index before a payload can become last-known-good data.

## Repository boundary

Both local and HTTP resources are byte-bounded. Remote responses are streamed in 64 KiB chunks; `Content-Length` is checked when present, and the cumulative body length is always enforced. Relative paths reject absolute paths, traversal components, unsafe separators, and unsupported characters.

Use HTTPS for remote production repositories. Plain HTTP remains supported for loopback tests and explicitly controlled private deployments for backward compatibility.

## Application-layer requirements

The library limits protect every caller, but public applications must additionally provide identity-aware rate limiting, bounded concurrency, an outer operation deadline shorter than the proxy timeout, safe output encoding, generic error messages, and deployment resource limits. See [Multi-worker API operations](OPERATIONS.md) for the normal/strict tiers and maintained systemd drop-ins.
