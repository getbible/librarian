# Changelog

All notable project changes are documented here.

## [2.0.0] - Unreleased

Search derives its matching strategy from the text. An application supplies a
query string; it no longer decides how a writing system should be read.

### Changed

- **Continuous scripts are searchable under the default criteria.** Han, kana,
  Hangul, Thai, Lao, Khmer, Myanmar and Tibetan are indexed as positioned
  character n-grams, so `whole_word` — the default — reaches them. Previously
  the whole clause between punctuation was one index token and no query could
  equal it, so a default search returned nothing.
- **`diacritics` defaults to `fold`** and takes `fold` or `exact`. Unaccented
  Greek, unpointed Hebrew and unvowelled Arabic now reach the text. The 1.x
  spellings `insensitive` and `sensitive` are accepted and map to the new
  values.
- **The substring minimum applies only to space-delimited scripts.** Two
  characters of Han, Hangul, Thai, Hebrew, Arabic or Devanagari are an ordinary
  word, answered exactly by the index rather than by a scan.
- `SEARCH_ENGINE_VERSION` is `4`. Downstream result caches keyed on it will
  invalidate.
- `getbible.search` is a package. All public names still import from `getbible`
  and from `getbible.search`.
- `cache_info()["indexes"]` reports `fold_diacritics` instead of `diacritics`.
- `warm_translation()` defaults to `diacritics="fold"` and returns an `analysis`
  block.

### Added

- Script-aware analysis: every run of text is classified by writing system
  through Unicode properties and analysed by that system's rules, so a
  translation added to the API later needs no code change here.
- Abjad stemming: a word behind an attached closed-class particle is reachable
  by its stem, so `אור` finds `וְהָאוֹר` and `بدء` finds `الْبَدْءِ`.
- Precomposed-letter folding for characters Unicode decomposition cannot reach,
  so `Duc Chua Troi` reaches `Ðức Chúa Trời`.
- Positional postings. A continuous run is verified by requiring its overlapping
  bigrams at consecutive positions, which is exact and reads no verse text.
- Trigram candidate generation for substring search.
- A process-wide corpus registry keyed by repository, translation and source
  SHA, so separate `GetBible` objects share one parsed, analysed copy.
- `SearchLimits.index_build_seconds`, bounding index construction separately
  from a request deadline.
- `query.analysis.script` in the response, reporting how the translation was
  read.
- A golden harness that derives expectations from a complete API translation by
  a plain text scan and requires the engine to agree. It skips when no tree is
  present.

### Fixed

- A query mixing scripts no longer loosens its space-delimited terms. Under 1.x
  an application flipped the whole query to substring on seeing one Han
  character, so `all` matched inside `shall`.
- Work is estimated from postings lengths. The previous estimator walked the
  whole vocabulary once per term and cost more than the search it guarded.
- An index build or lock wait no longer consumes the requesting call's
  deadline. Only that shared interval is excluded; validation, filtering and
  matching remain under one request-owned budget.
- Script runs are classified in one pass, and ASCII mark folding bypasses
  Unicode normalization, reducing cold English index construction without
  changing token output.
- Unicode join controls remain inside abjad and Brahmic words instead of
  creating separate whole-word postings for the fragments on either side.
- Isolated combining marks cannot create index terms or skew script reporting.
- A query of nothing but combining marks is rejected rather than treated as an
  empty term.
- Empty optional language or encoding labels in published translation metadata
  no longer prevent an otherwise valid corpus from loading.

### Deprecated

- `requires_substring_matching()` returns `False` for every query and should be
  deleted from callers. It remains exported so existing imports keep working.
- `allows_short_substring()` reports whether the substring floor is waived.

## [1.2.1] - 2026-07-29

### Added

- Deterministic multilingual search fixtures for Simplified and Traditional
  Chinese, Japanese, Korean, Arabic, Hebrew, Devanagari, Thai, Lao, Khmer,
  Myanmar, Persian join controls, and mixed-script queries.
- `requires_substring_matching()` as the shared Unicode-property detector for
  applications that offer automatic matching for continuous-writing scripts.
- Search response `engine_version` metadata and the matching
  `SEARCH_ENGINE_VERSION` constant for result-cache invalidation when matching
  semantics change without a translation SHA change.
- Per-item and aggregate character budgets for book-name and exclusion
  filters.

### Fixed

- Short substring searches now accept meaningful Han, kana, Hangul, and
  Unicode complex-context terms without lowering the global Latin/segmented
  script minimum.
- Substring matches now report every non-overlapping occurrence inside one
  uninterrupted token and charge that work conservatively.
- Grapheme-aware validation prevents punctuation and combining marks from
  padding undersized substring terms.
- ZWNJ and ZWJ no longer split otherwise continuous Arabic-script and Indic
  words.

## [1.2.0] - 2026-07-20

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
- A one-command local release gate that bootstraps the development toolchain,
  mirrors CI checks, and can append the opt-in live API integration suite.

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
