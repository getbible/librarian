# Development, CI, and releases

## Branch model

- `staging` receives integrated, tested changes.
- `master` is the releasable branch.
- Package publication is never triggered by an ordinary branch push.

## Local development

```bash
./scripts/run_release_gate.sh
```

This creates or reuses `.venv`, installs the development toolchain, and runs
the deterministic tests, lint, security and dependency scans, package checks,
and an isolated-wheel import. It avoids accidental reliance on globally
installed tools. See the [release gate](RELEASE_GATE.md) for the individual
commands, expected test diagnostics, and environment overrides.

## Deterministic tests

The default suite uses repository fixtures and does not depend on the public API. It covers references, book aliases, search criteria, result compatibility, concurrency, checksums, stale fallback, and pagination.

## Live integration

```bash
./scripts/run_release_gate.sh --live
```

GitHub runs the **Live API Integration** workflow weekly and on manual dispatch.
The scheduled job detects upstream API or fixture expectation drift without
making pull-request CI dependent on the network.

## CI artifacts

Every push and pull request to `master` or `staging`, plus a manual **CI**
workflow dispatch, runs:

- Python 3.10–3.14 deterministic tests;
- Ruff checks;
- Bandit and dependency-advisory checks;
- source and wheel builds;
- Twine package validation;
- installation and import of the wheel in isolation;
- upload of the built distributions as a GitHub Actions artifact.

The artifact can be downloaded and installed in a clean environment before release.

## Release preparation

1. Run the local release gate and resolve every failure.
2. Confirm the exact `staging` commit has a green **CI** workflow run.
3. Manually run **Live API Integration** for the same `staging` commit.
4. Review `CHANGELOG.md` and replace `Unreleased` with the release date.
5. Confirm the version in `pyproject.toml`.
6. Merge the exact release state into `master`.
7. Open the GitHub Actions **Release** workflow, choose **Run workflow**, and enter the version without the leading `v`.

The workflow freezes the current `master` SHA in its preparation job, requires
the entered version to match `pyproject.toml`, and passes that exact SHA to
every later job. It creates the corresponding `v<version>` tag only after all
tests and package validation pass, and refuses to move an existing tag.
Directly pushing a correctly formatted tag remains supported when the tagged
commit belongs to `master`.

## Automated release

The manually triggered release workflow:

1. Checks out the exact `master` release commit.
2. Verifies the entered version against the package version.
3. Runs the deterministic gate against the frozen commit on Python 3.10–3.14.
4. Builds source and wheel distributions once, runs `twine check`, installs the
   wheel in isolation, and creates GitHub build-provenance attestations.
5. Uploads those exact distributions as the immutable workflow artifact.
6. Creates and pushes the immutable `v<version>` tag.
7. Downloads the same artifact and publishes it through PyPI trusted publishing.
8. Downloads the same artifact again for the GitHub release; no rebuild occurs.

Configure the `pypi` GitHub environment and add this repository as a trusted
publisher for the `getbible` project in PyPI. No long-lived PyPI API token is
read by the workflow. Keep environment protection rules enabled so the OIDC
publication job receives approval independently of branch write access.

Every third-party Action is pinned to a complete immutable commit SHA. Update
the SHA and its adjacent version comment together after reviewing the upstream
release diff.
