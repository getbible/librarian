# Hardening and request budgets

`GetBible` applies a fail-closed layer before retrieval and search. Malformed, excessive, missing-translation, or unsafe requests are rejected before expensive translation-cache and persistent lock paths are entered.

## Default request and search limits

```python
from getbible import GetBible, RequestLimits, SearchLimits

bible = GetBible(
    request_limits=RequestLimits(
        max_input_length=1024,
        max_references=8,
        max_verses_per_reference=200,
        max_total_verses=200,
        max_search_offset=10_000,
        max_search_books=83,
        max_search_exclusions=32,
    ),
    search_limits=SearchLimits(
        max_query_length=500,
        min_substring_length=3,
        max_terms=32,
        max_exclusion_length=128,
        max_filter_values=83,
        max_work_units=500_000,
        max_response_bytes=8 * 1024 * 1024,
        deadline_seconds=10.0,
        strict_rate_tier_work_units=100_000,
    ),
    request_timeout=(3.05, 30.0),
    request_retries=3,
    max_response_bytes=128 * 1024 * 1024,
)
```

The parser has an independent hard ceiling of 200 verses per reference and validates a range before constructing it. Public services should normally configure stricter limits than library defaults.

Search work units are deterministic and derived from query length, term count, filter count, search mode, and pagination. Requests above `max_work_units` fail before corpus loading. Substring searches enforce a minimum term length. Response bytes are measured before returning data. The response `query.work` object reports work units, the strict-rate-tier decision, deadline, and encoded response size.

## Translation validation order

`search()` and `warm_translation()` validate the translation through the bounded negative TTL/LRU cache before the full-translation cache or its persistent file lock is entered. Repeated requests for a missing code therefore remain bounded and do not create an unbounded lock-file namespace.

## Returned-object ownership

`select()`, `search()`, `warm_translation()`, and `cache_info()` return deep copies. A caller can mutate any returned verse, metadata object, list, or dictionary without corrupting cached source objects or affecting subsequent requests.

## Typed failures

- `ReferenceValidationError`: malformed or unresolved reference; remains a `ValueError`.
- `RequestLimitError`: input, work, response volume, or deadline exceeded a finite budget; remains a `ValueError`.
- `TranslationNotFoundError`: missing translation; remains a `FileNotFoundError`.
- `RepositoryTimeoutError`: connect or read deadline exceeded.
- `RepositoryResponseTooLarge`: declared or streamed content exceeded the byte cap.
- `RepositoryError`: other repository access failures.

Applications should map these classes to stable public messages and log unexpected exceptions with a correlation identifier. Never echo raw exception strings to untrusted users.

## Repository boundary

Both local and HTTP resources are byte-bounded. Remote responses are streamed in finite chunks; `Content-Length` is checked when present, and cumulative body length is always enforced. Relative paths reject absolute paths, traversal components, unsafe separators, and unsupported characters.

Use HTTPS for remote production repositories. Plain HTTP remains supported only for loopback tests and explicitly controlled private deployments.

## Application-layer requirements

The Query and Search services must use separate rate tiers. Requests marked `strict_rate_tier=true` require the strict tier. The HTTP process must also enforce an outer deadline slightly above `SearchLimits.deadline_seconds`, bounded concurrency, safe output encoding, generic error messages, and systemd or container memory/task limits.
