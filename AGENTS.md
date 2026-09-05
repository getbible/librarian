# AGENTS.md

This file applies to the entire repository.

## Project purpose

GetBible Librarian is the Python retrieval and search library used by
getBible applications and by standalone Python programs. It must remain safe under threaded and multi-process API loads
while preserving its published JSON contracts.

The primary project home remains <https://git.vdm.dev/getBible/librarian>. GitHub at <https://github.com/getbible/librarian> hosts the deployment workflow, CI, releases, and PyPI publication path. Preserve both locations in project metadata and documentation.

## Branches

- `master` is the releasable branch.
- `staging` is the integration branch for completed, tested changes.
- Do not publish to PyPI from branch pushes. Releases are tag-driven.

## Critical public contracts

- `GetBible.select()` returns the established chapter-keyed dictionary.
- `GetBible.scripture()` returns that same dictionary encoded as JSON.
- `GetBible.search()` returns an envelope containing `query`, `results`, and `matches`.
- `SearchBible` is the canonical public class for configuring search behavior.
- Search derives its matching strategy from the writing system of the text and of the query. Do not reintroduce a public option, helper, or documented pattern that asks an application to choose how a script is read.
- A bare `search(query, translation)` call must return correct results for every translation the API publishes.
- `search()["results"]` must retain the same chapter and verse object structure as `select()`.
- Additive metadata is allowed. Removing or renaming existing scripture fields requires an explicit compatibility decision and migration documentation.
- Translation abbreviations are lowercase API identifiers and must be validated with a full match.

## Documentation scope

Document the library: how to call it, what it returns, how it caches, how it
is built and released. Do not document or prescribe how an application or
service built on it should be deployed, routed, rate limited, or operated;
that is outside the library's scope.

## Architecture rules

- Never create a cache-maintenance thread per `GetBible` instance.
- Use lazy freshness checks against the GetBible SHA endpoints.
- Verify full-translation bytes before replacing a last-known-good cache entry.
- Disk replacements must be atomic and coordinated between worker processes.
- Network sessions must not be reused across a process fork.
- Keep loaded translation corpora immutable. Build alternative analysed search indexes lazily.
- Corpora are shared process-wide through the registry keyed by repository, translation, and source SHA. Do not reintroduce per-instance corpus ownership.
- Index construction is bounded by `index_build_seconds`, never by a request deadline. A build that is abandoned must not leave the next request repeating it.
- Preserve bounded process-local caches and reference-counted keyed locks; a workload must not grow memory solely because new keys or translations are requested.
- Preserve `warm_translation()`, JSON-safe `cache_info()`, and orderly `close()` behavior when changing repository or cache internals.
- When a validated source SHA is unchanged, retain the existing corpus and built indexes while updating freshness metadata.
- Preserve the lightweight chapter path for reference-only requests; do not download an entire translation for `select()`.
- Never expose raw user regular expressions through the search interface.
- Keep default tests deterministic and independent of the live API.

## Development commands

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests benchmarks scripts examples
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

Run live integration tests deliberately:

```bash
GETBIBLE_RUN_LIVE_TESTS=1 .venv/bin/python -m unittest \
  tests.test_getbible tests.test_live_search -v
```

Run the search benchmark after warming or changing the search engine:

```bash
.venv/bin/python benchmarks/search_benchmark.py \
  --translation kjv --query "faith hope" --iterations 10000
```

Sweep every writing-system family after changing analysis or the index. A
search costs what its result set costs, so a family drifting away from the
others points at an analysis regression:

```bash
.venv/bin/python benchmarks/search_benchmark.py --sweep --iterations 200
```

## Test expectations

- Add offline fixture coverage for every new search criterion or response field.
- Test cache checksum rejection and stale fallback behavior.
- Test concurrent access when changing cache or corpus coordination.
- Run the live suite before a release.
- Benchmark common and rare terms before replacing or expanding the postings index.
- Cover every writing-system family when changing analysis: space-delimited, continuous, abjad, and Brahmic.
- Run the golden corpora suite against a real API tree before a release: `GETBIBLE_API_FIXTURES=<tree> .venv/bin/python -m unittest tests.test_golden_corpora`.

## Release expectations

1. Merge tested changes through `staging` into `master`.
2. Ensure `pyproject.toml` and `CHANGELOG.md` contain the intended version.
3. Confirm CI and live integration are green.
4. Tag the exact master commit as `v<project-version>`.
5. The release workflow verifies the tag, rebuilds, checks, publishes to PyPI, and creates the GitHub release.
