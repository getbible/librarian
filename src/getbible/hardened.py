"""Fail-closed public facade with request-level resource budgets."""

from __future__ import annotations

import copy
import json
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
        if self.max_verses_per_reference > 200:
            raise ValueError("max_verses_per_reference cannot exceed the parser ceiling of 200.")


@dataclass(frozen=True, slots=True)
class SearchLimits:
    """Deterministic search work, output, and deadline budgets."""

    max_query_length: int = 500
    min_substring_length: int = 3
    max_terms: int = 32
    max_exclusion_length: int = 128
    max_filter_values: int = 83
    max_work_units: int = 500_000
    max_response_bytes: int = 8 * 1024 * 1024
    deadline_seconds: float = 10.0
    strict_rate_tier_work_units: int = 100_000

    def __post_init__(self) -> None:
        integer_fields = (
            "max_query_length",
            "min_substring_length",
            "max_terms",
            "max_exclusion_length",
            "max_filter_values",
            "max_work_units",
            "max_response_bytes",
            "strict_rate_tier_work_units",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an integer.")
            if value < 1:
                raise ValueError(f"{name} must be positive.")
        if not isinstance(self.deadline_seconds, int | float) or isinstance(
            self.deadline_seconds, bool
        ):
            raise TypeError("deadline_seconds must be numeric.")
        if self.deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive.")
        if self.strict_rate_tier_work_units > self.max_work_units:
            raise ValueError("strict_rate_tier_work_units cannot exceed max_work_units.")


class GetBible(_BaseGetBible):
    """The public Librarian client with bounded parsing and typed failures."""

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
        search_limits: SearchLimits | None = None,
        negative_translation_cache_limit: int = 64,
        negative_translation_ttl: float = 300.0,
        max_response_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        self.request_limits = request_limits or RequestLimits()
        self.search_limits = search_limits or SearchLimits()
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
        """Return caller-owned verses after enforcing request limits."""
        code = self._validated_translation_code(abbreviation)
        self._validated_references(reference, code)
        if not self.valid_translation(code):
            raise TranslationNotFoundError(f"Translation ({code}) not found.")
        try:
            return copy.deepcopy(super().select(reference, code))
        except ReferenceValidationError:
            raise
        except ValueError as error:
            raise ReferenceValidationError(str(error)) from error

    def valid_reference(self, reference: str, abbreviation: str | None = "kjv") -> bool:
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
        """Search after deterministic validation and return caller-owned data."""
        started = time.monotonic()
        stripped_query, parsed, work_units = self._validated_search(query, criteria)
        code = self._validated_translation_code(abbreviation)
        if not self.valid_translation(code):
            raise TranslationNotFoundError(f"Translation ({code}) not found.")
        self._check_search_deadline(started)
        response = super().search(stripped_query, code, parsed)
        self._check_search_deadline(started)
        owned = copy.deepcopy(response)
        encoded_size = len(
            json.dumps(owned, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if encoded_size > self.search_limits.max_response_bytes:
            raise RequestLimitError(
                "Search response exceeds the configured response-volume budget."
            )
        owned["query"]["work"] = {
            "units": work_units,
            "strict_rate_tier": work_units > self.search_limits.strict_rate_tier_work_units,
            "deadline_seconds": float(self.search_limits.deadline_seconds),
            "response_bytes": encoded_size,
        }
        return owned

    def warm_translation(
        self,
        abbreviation: str | None = "kjv",
        *,
        case_sensitive: bool = False,
        diacritics: str = "sensitive",
    ) -> dict[str, Any]:
        """Warm only translations proven available before cache/lock entry."""
        code = self._validated_translation_code(abbreviation)
        if not self.valid_translation(code):
            raise TranslationNotFoundError(f"Translation ({code}) not found.")
        return copy.deepcopy(
            super().warm_translation(
                code,
                case_sensitive=case_sensitive,
                diacritics=diacritics,
            )
        )

    def cache_info(self) -> dict[str, Any]:
        state = copy.deepcopy(super().cache_info())
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
        state["search_limits"] = asdict(self.search_limits)
        state["active_translation_validation_locks"] = self._translation_validation_locks.size
        state["repository_max_response_bytes"] = self._repository.max_response_bytes
        return state

    def close(self) -> None:
        with self._missing_translations_guard:
            self._missing_translations.clear()
        super().close()

    def _validated_search(
        self,
        query: str,
        criteria: SearchBible | dict[str, Any] | str | None,
    ) -> tuple[str, SearchBible, int]:
        if not isinstance(query, str):
            raise SearchValidationError("Search query must be a string.")
        stripped_query = query.strip()
        if not stripped_query:
            raise SearchValidationError("Search query cannot be empty.")
        if len(stripped_query) > self.search_limits.max_query_length:
            raise RequestLimitError(
                f"Search query cannot exceed {self.search_limits.max_query_length} characters."
            )
        parsed = SearchBible.from_value(criteria)
        if parsed.offset > self.request_limits.max_search_offset:
            raise RequestLimitError(
                f"Search offset cannot exceed {self.request_limits.max_search_offset}."
            )
        if len(parsed.books) > min(
            self.request_limits.max_search_books,
            self.search_limits.max_filter_values,
        ):
            raise RequestLimitError("Search contains too many book filters.")
        if len(parsed.exclude) > self.request_limits.max_search_exclusions:
            raise RequestLimitError("Search contains too many exclusion filters.")
        if any(len(term) > self.search_limits.max_exclusion_length for term in parsed.exclude):
            raise RequestLimitError("Search exclusion term is too long.")
        terms = [term for term in stripped_query.split() if term]
        if len(terms) > self.search_limits.max_terms:
            raise RequestLimitError("Search contains too many terms.")
        if parsed.match == "substring" and any(
            len(term) < self.search_limits.min_substring_length for term in terms
        ):
            raise SearchValidationError(
                "Substring terms must contain at least "
                f"{self.search_limits.min_substring_length} characters."
            )
        filter_factor = max(1, len(parsed.books) + len(parsed.exclude))
        pagination_factor = parsed.offset + parsed.limit
        mode_factor = 4 if parsed.match == "substring" else 1
        phrase_factor = 2 if parsed.words == "phrase" else 1
        work_units = max(1, len(stripped_query)) * max(1, len(terms))
        work_units *= filter_factor * mode_factor * phrase_factor
        work_units += pagination_factor
        if work_units > self.search_limits.max_work_units:
            raise RequestLimitError("Search exceeds the configured deterministic work budget.")
        return stripped_query, parsed, work_units

    def _check_search_deadline(self, started: float) -> None:
        if time.monotonic() - started > self.search_limits.deadline_seconds:
            raise RequestLimitError("Search exceeded the configured cooperative deadline.")

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
                f"A request cannot contain more than {self.request_limits.max_references} references."
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
                    f"A request cannot select more than {self.request_limits.max_total_verses} verses."
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
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise TypeError(f"{name} must be numeric.")
        numeric = float(value)
        if not minimum <= numeric <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")
        return numeric
