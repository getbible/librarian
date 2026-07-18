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

### Fixed

- Translation and reference validation now validate complete input instead of accepted prefixes.
- Chapter and translation cache updates can no longer replace valid data with partial or checksum-mismatched downloads.
- PyPI publication no longer runs on every push to `master`.
- Concurrent cache eviction no longer invalidates active searches, and HTTP sessions can now be released explicitly at worker shutdown.

## [1.1.2] - 2023-12-11

- Stabilized reference validation and Hebrew reference coverage.
