"""Deterministic per-request budgets for search execution.

A budget bounds the work one *request* may do. It deliberately does not bound
index construction: an index is built once per translation and shared by every
later request, so charging it to whichever request happened to arrive first
made that request fail while leaving nothing cached, and the next request
repeated the work and failed the same way.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..exceptions import SearchDeadlineExceeded, SearchLimitError

__all__ = ["SearchBudget", "SearchLimits"]


@dataclass(frozen=True, slots=True)
class SearchLimits:
    """Per-search work, output, filter and deadline budgets."""

    max_work_units: int = 50_000_000
    max_response_bytes: int = 4 * 1024 * 1024
    max_query_length: int = 500
    max_query_terms: int = 64
    min_substring_length: int = 3
    max_books: int = 83
    max_book_length: int = 256
    max_books_length: int = 4_096
    max_exclusions: int = 32
    max_exclusion_length: int = 500
    max_exclusions_length: int = 4_000
    max_exclusion_terms: int = 64
    max_offset: int = 10_000
    max_limit: int = 1_000
    deadline_seconds: float = 5.0
    deadline_check_interval: int = 256
    #: Seconds an index build may take before it is abandoned. Separate from
    #: ``deadline_seconds`` because a build serves every later request.
    index_build_seconds: float = 120.0

    def __post_init__(self) -> None:
        integer_fields = (
            "max_work_units",
            "max_response_bytes",
            "max_query_length",
            "max_query_terms",
            "min_substring_length",
            "max_books",
            "max_book_length",
            "max_books_length",
            "max_exclusions",
            "max_exclusion_length",
            "max_exclusions_length",
            "max_exclusion_terms",
            "max_limit",
            "deadline_check_interval",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if (
            not isinstance(self.max_offset, int)
            or isinstance(self.max_offset, bool)
            or self.max_offset < 0
        ):
            raise ValueError("max_offset must be a non-negative integer.")
        for name in ("deadline_seconds", "index_build_seconds"):
            value = getattr(self, name)
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise TypeError(f"{name} must be numeric.")
        if not 0.001 <= float(self.deadline_seconds) <= 300.0:
            raise ValueError("deadline_seconds must be between 0.001 and 300 seconds.")
        if not 1.0 <= float(self.index_build_seconds) <= 3600.0:
            raise ValueError(
                "index_build_seconds must be between 1 and 3600 seconds."
            )

    def to_dict(self) -> dict[str, int | float]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


class SearchBudget:
    """One request's work reservation and cooperative deadline."""

    __slots__ = ("deadline", "limits", "started_at", "work_units")

    def __init__(self, limits: SearchLimits, seconds: float | None = None) -> None:
        self.limits = limits
        self.started_at = time.monotonic()
        self.deadline = self.started_at + float(
            limits.deadline_seconds if seconds is None else seconds
        )
        self.work_units = 0

    def reserve(self, units: int) -> None:
        if not isinstance(units, int) or isinstance(units, bool) or units < 0:
            raise ValueError("Search work units must be a non-negative integer.")
        if units > self.limits.max_work_units:
            raise SearchLimitError(
                f"Search requires {units} work units; the configured maximum is "
                f"{self.limits.max_work_units}."
            )
        self.work_units = max(self.work_units, units)
        self.check_deadline()

    def spend(self, units: int) -> None:
        """Add to the running total and fail once it passes the ceiling."""
        self.reserve(self.work_units + max(0, units))

    def extend(self, seconds: float) -> None:
        """Exclude shared work from this request's elapsed-time budget.

        Index construction and lock waiting serve the translation rather than
        one request. Shifting both timestamps preserves the original deadline
        for request-owned work and keeps elapsed telemetry accurate.
        """
        if seconds > 0:
            elapsed = float(seconds)
            self.deadline += elapsed
            self.started_at += elapsed

    def checkpoint(self, iteration: int = 0) -> None:
        if iteration % self.limits.deadline_check_interval == 0:
            self.check_deadline()

    def check_deadline(self) -> None:
        if time.monotonic() >= self.deadline:
            raise SearchDeadlineExceeded(
                f"Search exceeded its {float(self.limits.deadline_seconds):g}-second deadline."
            )

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)
