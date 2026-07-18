# Hardening and request budgets

`GetBible` now applies a fail-closed layer before the existing retrieval and search implementation. Existing result dictionaries and JSON output remain unchanged; only malformed, excessive, or unsafe requests are rejected earlier with typed exceptions.

## Default request limits

```python
from getbible import GetBible, RequestLimits

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
    request_timeout=(3.05, 30.0),
    request_retries=3,
    max_response_bytes=128 * 1024 * 1024,
)
```

The parser has an independent hard ceiling of 200 verses per reference and validates the range size before constructing it. A service may configure stricter values. Public chat and HTTP layers should normally do so.

Legacy open forms such as `John 1:2-` and `John 1:-5` retain their established single-verse meaning. Reversed ranges, zero, malformed punctuation, and ranges above the configured ceiling are rejected.

## Typed failures

- `ReferenceValidationError`: malformed or unresolved reference; remains a `ValueError`.
- `RequestLimitError`: input exceeded a finite work budget; remains a `ValueError`.
- `TranslationNotFoundError`: missing translation; remains a `FileNotFoundError`.
- `RepositoryTimeoutError`: connect or read deadline exceeded.
- `RepositoryResponseTooLarge`: declared or streamed content exceeded the byte cap.
- `RepositoryError`: other repository access failures.

Applications should map these classes to stable public messages and log unexpected exceptions with a correlation identifier. They should never echo raw exception strings to untrusted users.

## Translation validation

Positive translation data uses the existing bounded book cache. Missing translations use a separate bounded TTL cache so repeated invalid identifiers do not repeatedly reach the repository. Translation codes still require a complete match of the established identifier grammar.

## Repository boundary

Both local and HTTP resources are byte-bounded. Remote responses are streamed in 64 KiB chunks; `Content-Length` is checked when present, and the cumulative body length is always enforced. Relative paths reject absolute paths, traversal components, unsafe separators, and unsupported characters.

Use HTTPS for remote production repositories. Plain HTTP remains supported for loopback tests and explicitly controlled private deployments for backward compatibility.

## Application-layer requirements

The library limits protect every caller, but public applications must additionally provide identity-aware rate limiting, bounded concurrency, an outer operation deadline, safe output encoding, generic error messages, and deployment resource limits.
