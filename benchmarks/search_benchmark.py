"""Benchmark warm Librarian searches against a real translation corpus."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from getbible import GetBible, SearchBible


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="faith hope")
    parser.add_argument("--translation", default="kjv")
    parser.add_argument("--repository", default="https://api.getbible.net")
    parser.add_argument("--version", default="v2")
    parser.add_argument("--cache-dir")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--words", choices=("all", "any", "phrase"), default="all")
    parser.add_argument(
        "--match", choices=("whole_word", "substring"), default="whole_word"
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--sweep",
        action="store_true",
        help=(
            "Benchmark one query per writing-system family instead of a single "
            "query. A regression in any family shows up as a latency gap "
            "between families rather than as an outright failure."
        ),
    )
    return parser.parse_args()


#: One representative translation and query per family. A search costs what its
#: result set costs, so these are chosen to return comparable numbers of verses;
#: a family that drifts far from the others points at an analysis regression.
SWEEP = (
    ("alphabetic", "kjv", "faith"),
    ("alphabetic", "moderngreek", "\u03b1\u03b3\u03b1\u03c0\u03b7"),
    ("continuous", "cus", "\u795e"),
    ("continuous", "japkougo", "\u30a4\u30a8\u30b9"),
    ("continuous", "korean", "\uc0ac\ub791"),
    ("continuous", "thai", "\u0e1e\u0e23\u0e30\u0e40\u0e08\u0e49\u0e32"),
    ("abjad", "modernhebrew", "\u05d0\u05dc\u05d4\u05d9\u05dd"),
    ("abjad", "arabicsv", "\u0627\u0644\u0644\u0647"),
    ("brahmic", "mal1910", "\u0d26\u0d48\u0d35\u0d02"),
)


def sweep(arguments: argparse.Namespace) -> list[dict[str, Any]]:
    """Benchmark every writing-system family through the public API."""
    measured: list[dict[str, Any]] = []
    for family, translation, query in SWEEP:
        scoped = argparse.Namespace(**vars(arguments))
        scoped.translation = translation
        scoped.query = query
        scoped.sweep = False
        try:
            result = benchmark(scoped)
        except Exception as error:  # a missing translation must not stop the sweep
            measured.append(
                {"family": family, "translation": translation, "error": str(error)}
            )
            continue
        result["family"] = family
        measured.append(result)
    return measured


def benchmark(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.iterations < 1:
        raise ValueError("iterations must be greater than zero")
    if arguments.workers < 1:
        raise ValueError("workers must be greater than zero")

    bible = GetBible(
        repo_path=arguments.repository,
        version=arguments.version,
        cache_dir=arguments.cache_dir,
    )
    criteria = SearchBible(
        words=arguments.words,
        match=arguments.match,
        limit=arguments.limit,
    )

    startup_started = time.perf_counter()
    initial = bible.search(arguments.query, arguments.translation, criteria)
    startup_seconds = time.perf_counter() - startup_started
    expected = (initial["query"]["total"], initial["query"]["sha"])

    def execute(_: int) -> tuple[int, str]:
        response = bible.search(arguments.query, arguments.translation, criteria)
        return response["query"]["total"], response["query"]["sha"]

    started = time.perf_counter()
    if arguments.workers == 1:
        results = [execute(index) for index in range(arguments.iterations)]
    else:
        with ThreadPoolExecutor(max_workers=arguments.workers) as executor:
            results = list(executor.map(execute, range(arguments.iterations)))
    elapsed = time.perf_counter() - started

    if any(result != expected for result in results):
        raise RuntimeError("benchmark searches returned inconsistent results")

    return {
        "query": arguments.query,
        "translation": arguments.translation,
        "criteria": criteria.to_dict(),
        "translation_sha": expected[1],
        "total_matches": expected[0],
        "iterations": arguments.iterations,
        "workers": arguments.workers,
        "startup_seconds": startup_seconds,
        "elapsed_seconds": elapsed,
        "average_milliseconds": elapsed * 1000 / arguments.iterations,
        "queries_per_second": arguments.iterations / elapsed,
    }


def main() -> int:
    arguments = parse_arguments()
    if arguments.sweep:
        print(json.dumps(sweep(arguments), indent=2, sort_keys=True))
        return 0
    print(json.dumps(benchmark(arguments), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
