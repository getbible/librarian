# Development, CI, and releases

## Branch model

- `staging` receives integrated, tested changes.
- `master` is the releasable branch.
- Package publication is never triggered by an ordinary branch push.

## Local development

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests benchmarks scripts examples
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

## Deterministic tests

The default suite uses repository fixtures and does not depend on the public API. It covers references, book aliases, search criteria, result compatibility, concurrency, checksums, stale fallback, and pagination.

## Live integration

```bash
GETBIBLE_RUN_LIVE_TESTS=1 .venv/bin/python -m unittest \
  tests.test_getbible tests.test_live_search -v
```

GitHub runs the live suite weekly and on manual dispatch. The scheduled job detects upstream API or fixture expectation drift without making pull-request CI dependent on the network.

## CI artifacts

Every push and pull request to `master` or `staging` runs:

- Python 3.10–3.14 deterministic tests;
- Ruff checks;
- source and wheel builds;
- Twine package validation;
- upload of the built distributions as a GitHub Actions artifact.

The artifact can be downloaded and installed in a clean environment before release.

## Release preparation

1. Confirm `staging` CI is green.
2. Run the live integration workflow.
3. Review `CHANGELOG.md` and replace `Unreleased` with the release date.
4. Confirm the version in `pyproject.toml`.
5. Merge the exact release state into `master`.
6. Open the GitHub Actions **Release** workflow, choose **Run workflow**, and enter the version without the leading `v`.

The workflow always checks out `master`, requires the entered version to match `pyproject.toml`, and creates the corresponding `v<version>` tag only after tests and package validation pass. It refuses to move an existing tag. Directly pushing a correctly formatted tag remains supported for maintainers who need that route.

## Automated release

The manually triggered release workflow:

1. Checks out the exact `master` release commit.
2. Verifies the entered version against the package version.
3. Installs the project development tools and runs deterministic tests.
4. Builds source and wheel distributions and runs `twine check`.
5. Creates and pushes the immutable `v<version>` tag.
6. Publishes with the `PYPI_API_TOKEN` environment secret.
7. Creates a GitHub release with generated commit notes and both distributions.

Configure the `pypi` GitHub environment and its `PYPI_API_TOKEN` secret before running a release.
