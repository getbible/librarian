# Security policy

## Supported versions

Security fixes are applied to the latest released minor version. Older releases should be upgraded before reporting behavior that is already fixed in the current release.

## Reporting a vulnerability

Do not open a public issue for an unpatched vulnerability. Use GitHub's private vulnerability reporting feature for `getbible/librarian`, or contact the maintainers through the private address listed in the package metadata.

Include the affected version or commit, a minimal reproduction, expected impact, and any suggested mitigation. Do not include real Telegram tokens, private user content, or credentials.

## Security boundaries

The library treats references and translation identifiers as untrusted. It applies strict parsing, hard request budgets, bounded caches, TLS verification, explicit network timeouts, and typed failures. Applications remain responsible for authentication, inbound rate limits, output escaping, privacy, and host-level resource limits.
