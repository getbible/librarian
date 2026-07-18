"""Fail-closed public facade with request-level resource budgets."""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any

from ._keyed_locks import KeyedLockPool
from .exceptions import (
    ReferenceValidationError,
    RequestLimitError,
    SearchValidationError,
    TranslationNotFoundError,
)
from .getbible import GetBible as _BaseGetBible
from .search import SearchBible


@dataclass(frozen=True, slots=True)
class RequestLimits:
    """Per-call work budgets enforced before repository access."""

    max_input_length: int = 1024
    max_references: int = 8
    max_verses_per_reference: int = 200
    max_total_verses: int = 200
    max_search_offset: int = 10_000
    max_search_books: int = 83
    max_search_exclusions: int = 32

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an integer.")
            if value < 1:
                raise ValueError(f"{name} must be positive.")
        # The parser applies this hard ceiling before materializing a range.
        if self.max_verses_per_reference > 200:
            raise ValueError("max_verses_per_reference cannot exceed the parser ceiling of 200.")


class GetBible(_BaseGetBible):
    """The public Librarian client with bounded parsing and typed failures.

    Existing retrieval and search response contracts are preserved. Added
    limits reject abusive input before network or cache work is performed.
    """

    def __init__(
        self,
        repo_path: str | os.PathLike[str] = "https://api.getbible.net",
        version: str = "v2",
        cache_ttl: timedelta = timedelta(days=7),
        request_timeout: tuple[float, float] = (3.05, 30.0),
        request_retries: int = 3,
        cache_dir: str | os.PathLike[str] | None = None,
        strict_freshness: bool = False,
        reference_cache_limit: int | None = 5000,
        books_cache_limit: int | None = 64,
        chapter_cache_limit: int | None = 2048,
        search_corpus_limit: int | None = 4,
        translation_cache_limit: int | None = 4,
        cache_ttl_jitter: float = 0.1,
        *,
        request_limits: RequestLimits | None = None,
        negative_translation_cache_limit: int = 64,
        negative_translation_ttl: float = 300.0,
        max_response_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        self.request_limits = request_limits or RequestLimits()
        self._negative_translation_cache_limit = self._bounded_integer(
            "negative_translation_cache_limit",
            negative_translation_cache_limit,
            minimum=1,
            maximum=10_000,
        )
        self._negative_translation_ttl = self._bounded_float(
            "negative_translation_ttl",
            negative_translation_ttl,
            minimum=1.0,
            maximum=86_400.0,
        )
        super().__init__(
            repo_path=repo_path,
            version=version,
            cache_ttl=cache_ttl,
            request_timeout=request_timeout,
            request_retries=request_retries,
            cache_dir=cache_dir,
            strict_freshness=strict_freshness,
            reference_cache_limit=reference_cache_limit,
            books_cache_limit=books_cache_limit,
            chapter_cache_limit=chapter_cache_limit,
            search_corpus_limit=search_corpus_limit,
            translation_cache_limit=translation_cache_limit,
            cache_ttl_jitter=cache_ttl_jitter,
        )
        self._repository.max_response_bytes = self._bounded_integer(
            "max_response_bytes",
            max_response_bytes,
            minimum=1,
            maximum=1024**3,
        )
        self._missing_translations: OrderedDict[str, float] = OrderedDict()
        self._missing_translations_guard = threading.Lock()
        self._translation_validation_locks = KeyedLockPool()
        self._negative_translation_hits = 0
        self._negative_translation_misses = 0
        self._negative_translation_evictions = 0

    def select(self, reference: str, abbreviation: str | None = "kjv") -> dict[str, Any]:
        """Return verses after enforcing reference and total-work limits."""
        code = self._validated_translation_code(abbreviation)
        self._validated_references(reference, code)
        if not self.valid_translation(code):
            raise TranslationNotFoundError(f"Translation ({code}) not found.")
        try:
            return super().select(reference, code)
        except ReferenceValidationError:
            raise
        except ValueError as error:
            raise ReferenceValidationError(str(error)) from error

    def valid_reference(self, reference: str, abbreviation: str | None = "kjv") -> bool:
        """Return whether one bounded reference is structurally resolvable."""
        if not isinstance(reference, str) or len(reference) > self.request_limits.max_input_length:
            return False
        return super().valid_reference(reference, abbreviation)

    def valid_translation(self, abbreviation: str) -> bool:
        """Validate a translation with a bounded negative-result TTL cache."""
        try:
            code = self._validated_translation_code(abbreviation)
        except (TypeError, ValueError):
            return False

        if self._negative_translation_cached(code):
            return False
        with self._translation_validation_locks.hold(code):
            if self._negative_translation_cached(code):
                return False
            available = super().valid_translation(code)
            if available:
                with self._missing_translations_guard:
                    self._missing_translations.pop(code, None)
                return True
            self._remember_missing_translation(code)
            return False

    def search(
        self,
        query: str,
        abbreviation: str | None = "kjv",
        criteria: SearchBible | dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """Search only after cheap input and criteria checks have passed."""
        if not isinstance(query, str):
            raise SearchValidationError("Search query must be a string.")
        stripped_query = query.strip()
        if not stripped_query:
            raise SearchValidationError("Search query cannot be empty.")
        if len(stripped_query) > 500:
            raise RequestLimitError("Search query cannot exceed 500 characters.")
        parsed = SearchBible.from_value(criteria)
        if parsed.offset > self.request_limits.max_search_offset:
            raise RequestLimitError(
                f"Search offset cannot exceed {self.request_limits.max_search_offset}."
            )
        if len(parsed.books) > self.request_limits.max_search_books:
            raise RequestLimitError(
                f"Search cannot select more than {self.request_limits.max_search_books} books."
            )
        if len(parsed.exclude) > self.request_limits.max_search_exclusions:
            raise RequestLimitError(
                "Search cannot contain more than "
                f"{self.request_limits.max_search_exclusions} exclusions."
            )
        return super().search(stripped_query, abbreviation, parsed)

    def cache_info(self) -> dict[str, Any]:
        """Return base telemetry plus request and negative-cache limits."""
        state = super().cache_info()
        now = time.monotonic()
        with self._missing_translations_guard:
            self._purge_expired_missing(now)
            state["negative_translations"] = {
                "size": len(self._missing_translations),
                "limit": self._negative_translation_cache_limit,
                "ttl_seconds": self._negative_translation_ttl,
                "hits": self._negative_translation_hits,
                "misses": self._negative_translation_misses,
                "evictions": self._negative_translation_evictions,
            }
        state["request_limits"] = asdict(self.request_limits)
        state["active_translation_validation_locks"] = self._translation_validation_locks.size
        state["repository_max_response_bytes"] = self._repository.max_response_bytes
        return state

    def close(self) -> None:
        with self._missing_translations_guard:
            self._missing_translations.clear()
        super().close()

    def _validated_references(self, reference: str, abbreviation: str) -> None:
        if not isinstance(reference, str):
            raise ReferenceValidationError("Scripture reference must be a string.")
        if len(reference) > self.request_limits.max_input_length:
            raise RequestLimitError(
                f"Reference input cannot exceed {self.request_limits.max_input_length} characters."
            )
        references = reference.split(";")
        if len(references) > self.request_limits.max_references:
            raise RequestLimitError(
                "A request cannot contain more than "
                f"{self.request_limits.max_references} references."
            )

        total_verses = 0
        parser = self._GetBible__get
        for raw_reference in references:
            item = raw_reference.strip()
            if not item:
                raise ReferenceValidationError("Invalid empty reference.")
            parsed = parser.ref(item, abbreviation)
            selected = len(parsed.verses)
            if selected > self.request_limits.max_verses_per_reference:
                raise RequestLimitError(
                    "A reference cannot select more than "
                    f"{self.request_limits.max_verses_per_reference} verses."
                )
            total_verses += selected
            if total_verses > self.request_limits.max_total_verses:
                raise RequestLimitError(
                    "A request cannot select more than "
                    f"{self.request_limits.max_total_verses} verses."
                )

    def _negative_translation_cached(self, code: str) -> bool:
        now = time.monotonic()
        with self._missing_translations_guard:
            self._purge_expired_missing(now)
            expires_at = self._missing_translations.get(code)
            if expires_at is None:
                self._negative_translation_misses += 1
                return False
            self._missing_translations.move_to_end(code)
            self._negative_translation_hits += 1
            return expires_at > now

    def _remember_missing_translation(self, code: str) -> None:
        expires_at = time.monotonic() + self._negative_translation_ttl
        with self._missing_translations_guard:
            self._missing_translations[code] = expires_at
            self._missing_translations.move_to_end(code)
            while len(self._missing_translations) > self._negative_translation_cache_limit:
                self._missing_translations.popitem(last=False)
                self._negative_translation_evictions += 1

    def _purge_expired_missing(self, now: float) -> None:
        expired = [
            code for code, expires_at in self._missing_translations.items() if expires_at <= now
        ]
        for code in expired:
            self._missing_translations.pop(code, None)

    @staticmethod
    def _bounded_integer(name: str, value: int, *, minimum: int, maximum: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an integer.")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")
        return value

    @staticmethod
    def _bounded_float(
        name: str,
        value: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"{name} must be numeric.")
        numeric = float(value)
        if not minimum <= numeric <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")
        return numeric
