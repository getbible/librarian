# Release gate

A release is eligible only when all of the following are true:

1. Unit and hardening tests pass on every supported Python version.
2. The huge-range, malformed-suffix, reversed-range, translation-cache, timeout, invalid-JSON, and total-work regressions pass.
3. Ruff, Bandit, dependency audit, and secret scan pass.
4. The wheel and source distribution build successfully and `twine check` passes.
5. The built wheel is installed into a clean environment and its offline test suite passes.
6. The release commit is tagged intentionally and the protected `pypi` environment approves publication.
7. A rollback is available by reinstalling the preceding package version.

Production applications should additionally perform a concurrency test, upstream failure injection, a bounded-memory soak test, and a local-data fallback test before adopting a new release.
