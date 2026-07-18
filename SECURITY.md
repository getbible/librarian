# Security policy

## Supported code

Security fixes are developed on `staging`, validated by the complete CI matrix, and released through the documented release workflow. Production users should run the newest published release and use finite cache, request, and repository limits.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, private data, or a proof of concept that could harm a running service. Use GitHub private vulnerability reporting when available, or contact `getbible@vdm.io` with:

- the affected version or commit;
- the smallest safe reproduction;
- expected and observed behavior;
- impact and any known mitigations.

Never include a Telegram token or other production secret. Rotate a secret immediately if it may have been exposed.

## Security invariants

A change must not remove or bypass these controls:

- references are fully validated and bounded before verse ranges are materialized;
- one call has finite reference, verse, query, cache, timeout, retry, and response-size budgets;
- malformed input never silently resolves to a different verse;
- repository paths remain inside the configured source root;
- remote requests use explicit connect/read timeouts and bounded retries;
- raw repository or internal exceptions are not intended as end-user messages;
- deterministic tests, package checks, Bandit, and dependency auditing remain required CI gates.
