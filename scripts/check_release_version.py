"""Verify that a release tag matches the package version in pyproject.toml."""

from __future__ import annotations

import sys
from pathlib import Path

import tomllib


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: check_release_version.py <tag>", file=sys.stderr)
        return 2

    with Path("pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    expected = f"v{version}"
    actual = sys.argv[1]
    if actual != expected:
        print(
            f"Release tag {actual!r} does not match package version {expected!r}.",
            file=sys.stderr,
        )
        return 1
    print(f"Release tag {actual} matches package version {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
