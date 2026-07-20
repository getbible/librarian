# Security and reliability release gate

A staging commit is releasable only when every item below passes without suppressing or deleting an existing assertion.

## Automated gate

```bash
python -m pip install -r requirements-dev.txt
python -m compileall -q src tests
python -m unittest discover -s tests -v
ruff check src tests benchmarks scripts examples
bandit -q -r src/getbible -x src/getbible/data
python -m pip_audit
python -m build
python -m twine check dist/*
```

CI runs deterministic tests on Python 3.10 through 3.14, then installs and imports the built wheel in an isolated environment. Live API integration remains a separate opt-in workflow so the deterministic gate cannot be made flaky by an external service.

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
