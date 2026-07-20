# Changelog

All notable project changes are documented here.

## [1.2.0] - Unreleased

### Added

- JSON-friendly scripture search with all-word, any-word, phrase, whole-word, substring, case, diacritic, testament, deuterocanonical, book, exclusion, proximity, relevance, and pagination criteria.
- `SearchBible`, the canonical public class for validated search behavior, with a compatibility alias for the earlier development name.
- Search response metadata with exact totals, source SHA, cache state, ordered match metadata, and the established grouped scripture result objects.
- Persistent checksum-validated full-translation caching with atomic cross-worker replacement and last-known-good fallback.
- Deterministic offline search, concurrency, integrity, and cache tests.
- Scheduled live API integration tests and a standalone search benchmark.
- Repository architecture, operations, caching, search, usage, and release documentation.
- Explicit translation/index warm-up, JSON-safe cache telemetry, and orderly HTTP session shutdown APIs.
- Configurable bounded LRU retention for references, books, chapters, translation snapshots, and search corpora.
- Typed reference, work-budget, translation, timeout, and oversized-response exceptions.
- Request-level reference, verse, search-pagination, and response-body budgets.
- Bounded negative translation caching and parser fuzz/regression coverage.
- Deterministic `SearchLimits`, response-volume accounting, substring minimums, cooperative deadlines, and pre-execution `SearchBible.expensive` classification.
- Atomic source-generation manifests, reader/transition barriers, stable external cache namespaces, failure-serialized purge callbacks, and worker cache invalidation.
- Maintained Query and Search systemd resource-limit drop-ins.

### Changed

- Documented independent `query.getbible.net` reference and `search.getbible.net` search service contracts, including GET-only filtering, cache isolation, and local/remote repository operation.
- Replaced per-instance monthly cache threads with lazy seven-day freshness validation.
- Added thread-local, retrying HTTP sessions that are recreated after process forks.
- Made reference caching translation-aware and genuinely least-recently-used.
- Improved Unicode normalization for book names and references.
- Aligned supported Python versions, dependency metadata, CI, package builds, and tag-driven releases.
- Added an Actions-driven release path that validates an entered version and creates its matching Git tag automatically.
- Local filesystem repositories now accept `pathlib.Path` values directly and are parity-tested against HTTP repositories.
- Added deterministic per-worker freshness jitter to spread repository checks without extending the configured cache TTL.
- Unchanged translation SHAs now preserve existing corpora and built search indexes instead of decoding and rebuilding them.
- Replaced permanently retained keyed locks with reference-counted per-resource coordination.
- Repository downloads now stream into a finite byte budget and validate path, timeout, retry, and backoff configuration.
- CI now compiles every source file and runs static security and dependency-advisory scans without removing any existing test or package checks.
- Full translations now use validation-versioned, content-addressed immutable payloads with atomic metadata commits and independent books-index validation.
- Release publication now freezes one `master` commit, gates Python 3.10–3.14, builds once, attests the distributions, and uses PyPI trusted publishing.

### Fixed

- Translation and reference validation now validate complete input instead of accepted prefixes.
- Chapter and translation cache updates can no longer replace valid data with partial or checksum-mismatched downloads.
- PyPI publication no longer runs on every push to `master`.
- Concurrent cache eviction no longer invalidates active searches, and HTTP sessions can now be released explicitly at worker shutdown.
- Verse ranges are bounded before `range()` is materialized, closing a remote memory-exhaustion path.
- Reversed and malformed ranges fail closed instead of returning a different verse.
- Cached `BookReference.verses` lists can no longer be mutated by callers.
- Search and warm-up now reject missing translations through the bounded negative cache before entering abbreviation-specific translation payload or lock paths.
- Full-translation and chapter SHA enforcement, complete nested validation, and last-known-good preservation now cover malformed upstream refreshes.
- Returned Query and Search verses and metadata are deep copies independent of every internal cache.

## [1.1.2] - 2023-12-11

- Stabilized reference validation and Hebrew reference coverage.
