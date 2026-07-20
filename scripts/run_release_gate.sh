#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/run_release_gate.sh [--live]

Create or reuse the project virtual environment, install the development
toolchain, and run the local release gate. Pass --live to run the opt-in live
API integration tests after the deterministic gate succeeds.

Environment variables:
  PYTHON     Python interpreter used to create .venv (default: python3)
  VENV_DIR   Virtual environment path (default: <repository>/.venv)
EOF
}

run_live=0
case "${1:-}" in
  "") ;;
  --live) run_live=1 ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

python_command="${PYTHON:-python3}"
venv_dir="${VENV_DIR:-$repository_root/.venv}"

if [[ ! -x "$venv_dir/bin/python" ]]; then
  echo "Creating virtual environment with $python_command"
  "$python_command" -m venv --clear --copies "$venv_dir"
fi

python="$venv_dir/bin/python"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/getbible-release-gate.XXXXXX")"
trap 'rm -rf -- "$work_dir"' EXIT

echo "Using $($python --version) from $venv_dir"
echo "Installing the project development toolchain"
"$python" -m pip install --upgrade pip
"$python" -m pip install -r requirements-dev.txt

echo "Compiling source and tests"
"$python" -m compileall -q src tests

echo "Running deterministic tests"
test_log="$work_dir/deterministic-tests.log"
if "$python" -m unittest discover -s tests -v >"$test_log" 2>&1; then
  tail -n 5 "$test_log"
else
  tail -n 200 "$test_log" >&2
  exit 1
fi

echo "Running lint and security checks"
"$venv_dir/bin/ruff" check src tests benchmarks scripts examples
"$venv_dir/bin/bandit" -q -r src/getbible -x src/getbible/data
"$python" -m pip_audit --cache-dir "$work_dir/pip-audit-cache"

echo "Building and validating distributions"
dist_dir="$work_dir/dist"
"$python" -m build --outdir "$dist_dir"
"$python" -m twine check "$dist_dir"/*

wheels=("$dist_dir"/*.whl)
if [[ ! -f "${wheels[0]}" ]]; then
  echo "The build did not produce a wheel." >&2
  exit 1
fi

echo "Installing the wheel in an isolated environment"
wheel_venv="$work_dir/wheel-venv"
"$python" -m venv --copies "$wheel_venv"
"$wheel_venv/bin/python" -m pip install "${wheels[0]}"
(
  cd "$work_dir"
  "$wheel_venv/bin/python" -c "from getbible import GetBible, RequestLimits, SearchBible, SearchLimits, SourceGeneration; assert SearchBible().limit == 100; assert RequestLimits().max_references == 8; assert SearchLimits().max_work_units == 50000000; assert SourceGeneration('test', 0, 'initial', 0).cache_namespace == 'test:g0'; GetBible().close()"
)

if [[ "$run_live" -eq 1 ]]; then
  echo "Running opt-in live API integration tests"
  live_cache="$work_dir/live-cache"
  GETBIBLE_RUN_LIVE_TESTS=1 GETBIBLE_CACHE_DIR="$live_cache" \
    "$python" -m unittest tests.test_getbible tests.test_live_search -v
fi

echo "Local release gate passed."
