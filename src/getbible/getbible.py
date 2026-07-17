"""Public Librarian facade for reference-based scripture selection."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from .exceptions import CacheIntegrityError, RepositoryResourceNotFound
from .getbible_reference import BookReference, GetBibleReference
from .repository_client import RepositoryClient


@dataclass
class _CacheEntry:
    data: dict[str, Any]
    loaded_at: float
    sha: Optional[str] = None


class GetBible:
    """Retrieve scripture from a GetBible API-compatible repository.

    Cache refresh is lazy and request-driven. Constructing this class does not
    create background threads, making it safe for threaded and multi-worker API
    deployments.
    """

    WORD_OPTIONS = {'allwords', 'anywords', 'exactwords'}
    MATCH_OPTIONS = {'exactmatch', 'partialmatch'}
    CASE_OPTIONS = {'caseinsensitive', 'casesensitive'}
    TARGET_OPTIONS = (
        {'allbooks', 'oldtestament', 'newtestament', 'deuterocanon'}
        | set(map(str, range(1, 84)))
    )
    _TRANSLATION_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,29}")

    def __init__(
        self,
        repo_path: str = "https://api.getbible.net",
        version: str = 'v2',
        cache_ttl: timedelta = timedelta(days=7),
        request_timeout: tuple[float, float] = (3.05, 60.0),
        request_retries: int = 3,
    ) -> None:
        self.__get = GetBibleReference()
        self._repository = RepositoryClient(
            repo_path=repo_path,
            version=version,
            timeout=request_timeout,
            retries=request_retries,
        )
        self._cache_ttl_seconds = max(0.0, cache_ttl.total_seconds())
        self.__books_cache: dict[str, _CacheEntry] = {}
        self.__chapters_cache: dict[str, _CacheEntry] = {}
        self._cache_guard = threading.RLock()
        self._resource_locks: dict[str, threading.Lock] = {}

    def select(self, reference: str, abbreviation: Optional[str] = 'kjv') -> dict[str, Any]:
        """Return Bible verses using the established grouped result contract."""
        abbreviation = self._validated_translation_code(abbreviation)
        self.__check_translation(abbreviation)
        result: dict[str, Any] = {}
        for raw_reference in reference.split(';'):
            ref = raw_reference.strip()
            if not ref:
                raise ValueError("Invalid empty reference.")
            try:
                book_reference = self.__get.ref(ref, abbreviation)
            except ValueError as error:
                raise ValueError(f"Invalid reference '{ref}'.") from error
            self.__set_verse(abbreviation, book_reference, result)
        return result

    def scripture(self, reference: str, abbreviation: Optional[str] = 'kjv') -> str:
        """Return :meth:`select` output encoded as JSON."""
        return json.dumps(self.select(reference, abbreviation), ensure_ascii=False)

    def valid_reference(self, reference: str, abbreviation: Optional[str] = 'kjv') -> bool:
        """Return whether ``reference`` is structurally resolvable."""
        return self.__get.valid(reference, abbreviation)

    def valid_translation(self, abbreviation: str) -> bool:
        """Return whether a translation is available in the repository."""
        try:
            code = self._validated_translation_code(abbreviation)
        except (TypeError, ValueError):
            return False

        key = f"books:{code}"
        lock = self._resource_lock(key)
        with lock:
            with self._cache_guard:
                entry = self.__books_cache.get(code)
            if entry is not None and self._is_fresh(entry):
                return True
            try:
                books = self._repository.fetch_json(f"{code}/books.json")
            except RepositoryResourceNotFound:
                return False
            with self._cache_guard:
                self.__books_cache[code] = _CacheEntry(books, time.monotonic())
            return True

    def valid_limit(self, limit: str) -> bool:
        """Validate the legacy compact search-limit notation."""
        if not isinstance(limit, str):
            return False
        parts = limit.split('-')
        if len(parts) != 4:
            return False
        words, match, case, target = parts
        return (
            words in self.WORD_OPTIONS
            and match in self.MATCH_OPTIONS
            and case in self.CASE_OPTIONS
            and target in self.TARGET_OPTIONS
        )

    def _validated_translation_code(self, abbreviation: Optional[str]) -> str:
        if not isinstance(abbreviation, str):
            raise TypeError("Translation abbreviation must be a string.")
        code = abbreviation.casefold()
        if self._TRANSLATION_PATTERN.fullmatch(code) is None:
            raise ValueError(f"Invalid translation abbreviation '{abbreviation}'.")
        return code

    def _resource_lock(self, key: str) -> threading.Lock:
        with self._cache_guard:
            return self._resource_locks.setdefault(key, threading.Lock())

    def _is_fresh(self, entry: _CacheEntry) -> bool:
        return time.monotonic() - entry.loaded_at < self._cache_ttl_seconds

    def __set_verse(
        self,
        abbreviation: str,
        book_ref: BookReference,
        result: dict[str, Any],
    ) -> None:
        cache_key = f"{abbreviation}_{book_ref.book}_{book_ref.chapter}"
        chapter_data = self._chapter(abbreviation, book_ref.book, book_ref.chapter)

        for verse in book_ref.verses:
            verse_info = chapter_data["verses"].get(str(verse))
            if not verse_info:
                raise ValueError(
                    f"Verse {verse} not found in book {book_ref.book}, "
                    f"chapter {book_ref.chapter}."
                )

            if cache_key in result:
                existing_verses = {str(item["verse"]) for item in result[cache_key]["verses"]}
                if str(verse) not in existing_verses:
                    result[cache_key]["verses"].append(verse_info)
                if book_ref.reference not in result[cache_key]["ref"]:
                    result[cache_key]["ref"].append(book_ref.reference)
                continue

            result[cache_key] = {
                key: value for key, value in chapter_data.items() if key != "verses"
            }
            result[cache_key]["ref"] = [book_ref.reference]
            result[cache_key]["verses"] = [verse_info]

    def _chapter(self, abbreviation: str, book: int, chapter: int) -> dict[str, Any]:
        cache_key = f"{abbreviation}_{book}_{chapter}"
        lock = self._resource_lock(f"chapter:{cache_key}")
        with lock:
            with self._cache_guard:
                entry = self.__chapters_cache.get(cache_key)
            if entry is not None and self._is_fresh(entry):
                return entry.data

            if entry is not None and entry.sha:
                try:
                    remote_sha = self._repository.fetch_text(
                        f"{abbreviation}/{book}/{chapter}.sha"
                    ).strip()
                except RepositoryResourceNotFound:
                    remote_sha = ""
                if remote_sha and remote_sha == entry.sha:
                    entry.loaded_at = time.monotonic()
                    return entry.data

            relative_path = f"{abbreviation}/{book}/{chapter}.json"
            try:
                raw = self._repository.fetch_bytes(relative_path)
            except RepositoryResourceNotFound as error:
                raise FileNotFoundError(
                    f"Chapter:{chapter} in book:{book} for {abbreviation} not found."
                ) from error
            try:
                chapter_data = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CacheIntegrityError(
                    f"Invalid chapter JSON for {abbreviation} {book}:{chapter}."
                ) from error
            if not isinstance(chapter_data, dict) or not isinstance(
                chapter_data.get("verses"), list
            ):
                raise CacheIntegrityError(
                    f"Invalid chapter structure for {abbreviation} {book}:{chapter}."
                )

            chapter_data["verses"] = {
                str(verse["verse"]): verse for verse in chapter_data["verses"]
            }
            loaded = _CacheEntry(
                data=chapter_data,
                loaded_at=time.monotonic(),
                sha=hashlib.sha1(raw).hexdigest(),
            )
            with self._cache_guard:
                self.__chapters_cache[cache_key] = loaded
            return chapter_data

    def __check_translation(self, abbreviation: str) -> None:
        if not self.valid_translation(abbreviation):
            raise FileNotFoundError(f"Translation ({abbreviation}) not found.")
