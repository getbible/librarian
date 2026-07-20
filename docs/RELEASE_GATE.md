# Security and reliability release gate

A staging commit is releasable only when every item below passes without suppressing or deleting an existing assertion.

## Choose the right gate

GitHub Actions is the authoritative release gate because it validates every
supported Python version in a clean runner:

1. Open **Actions** in GitHub.
2. Select **CI** and choose **Run workflow** for the branch or commit under
   review. CI runs deterministic tests on Python 3.10 through 3.14, followed by
   lint, security, dependency, package, and isolated-wheel checks.
3. Select **Live API Integration** and choose **Run workflow** before a release.
   This separate job checks the public API without making pull-request CI
   dependent on an external service. It also runs on a weekly schedule.

Both workflows support manual dispatch. A pull request to `staging` or `master`
also starts CI automatically.

## One-command local gate

From the repository root, run:

```bash
./scripts/run_release_gate.sh
```

The script creates or reuses `.venv`, installs `requirements-dev.txt`, and runs
the same categories of deterministic, quality, dependency, build, and isolated
wheel checks as CI on the current Python interpreter. It deliberately uses the
tools inside `.venv`; global or Snap installations of Ruff, Bandit, Build,
Twine, or pip-audit are neither needed nor used.

To append the opt-in live API checks:

```bash
./scripts/run_release_gate.sh --live
```

Set `PYTHON=python3.14` to choose the interpreter when creating `.venv`, or set
`VENV_DIR` to use a different virtual-environment directory. Delete or rename
an existing environment first if its Python interpreter needs to change.

The local gate validates one Python interpreter. A green GitHub **CI** run is
still required for the complete Python 3.10–3.14 matrix.

## Manual local commands

If an individual check needs investigation, the equivalent commands are:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests benchmarks scripts examples
.venv/bin/bandit -q -r src/getbible -x src/getbible/data
.venv/bin/python -m pip_audit --cache-dir .cache/pip-audit
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

Installing only the runtime package with `.venv/bin/python -m pip install -e .`
does **not** install the release tools. Use `requirements-dev.txt`, which installs
the package's `dev` extra, before invoking the manual commands.

## Reading deterministic test output

- Twelve skipped live tests in the default suite are expected. They run only
  when `GETBIBLE_RUN_LIVE_TESTS=1` is set.
- The last-known-good refresh regression intentionally feeds an invalid corpus
  to the cache. A logged `CacheIntegrityError` followed by that test's `ok` and
  a final `OK` suite result is expected; it proves the invalid refresh was
  rejected while the valid cached corpus remained available.
- A nonzero command exit status or a final `FAILED`/`ERROR` result is a real
  gate failure. The local script prints the final summary on success and the
  last 200 log lines on failure, matching CI's failure diagnostics.

## Required adversarial cases

- a range such as `John 1:1-999999999` terminates without proportional allocation;
- malformed or reversed ranges never resolve to verse 1 or another unintended verse;
- per-reference and aggregate verse budgets are both enforced;
- repeated missing translations use bounded negative caching;
- missing Search and warm-up translations are rejected before abbreviation-specific translation payload paths and locks;
- oversized local and remote repository bodies are rejected;
- repository traversal is rejected;
- blank and excessive search inputs fail before translation loading;
- substring, deterministic work, output-volume, filter, and cooperative deadline budgets fail closed;
- full corpora and independent books indexes are completely validated before a versioned content-addressed payload is committed;
- production full-translation and chapter checksums are required and compared;
- invalid upstream refreshes preserve the last-known-good corpus;
- Query and Search return deep copies that cannot corrupt cached verses or metadata;
- source-generation purge failures do not commit and successful transitions invalidate other workers;
- the release artifact is built once, attested, trusted-published, and reused for the GitHub release;
- all historical parser, Unicode, search, cache, local/HTTP parity, and packaging tests still pass.

## Operational gate

Before deployment, verify explicit memory and task limits, restart behavior, secret-file permissions, log redaction, metrics collection, rollback to the previous release, and a bounded outage response when the upstream repository is unavailable.
