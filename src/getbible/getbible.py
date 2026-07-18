"""Public Librarian facade for reference-based scripture selection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .exceptions import CacheIntegrityError, RepositoryResourceNotFound
from .getbible_reference import BookReference, GetBibleReference
from .repository_client import RepositoryClient
from .search import SearchBible, SearchEngine, SearchHit, TranslationCorpus
from .translation_cache import TranslationCache


@dataclass
class _CacheEntry:
    data: dict[str, Any]
    loaded_at: float
    sha: str | None = None


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
        repo_path: str | os.PathLike[str] = "https://api.getbible.net",
        version: str = 'v2',
        cache_ttl: timedelta = timedelta(days=7),
        request_timeout: tuple[float, float] = (3.05, 60.0),
        request_retries: int = 3,
        cache_dir: str | os.PathLike[str] | None = None,
        strict_freshness: bool = False,
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
        self._translation_cache = TranslationCache(
            repository=self._repository,
            refresh_seconds=self._cache_ttl_seconds,
            cache_dir=cache_dir,
            strict_freshness=strict_freshness,
        )
        self._search_corpora: dict[str, TranslationCorpus] = {}

    def select(self, reference: str, abbreviation: str | None = 'kjv') -> dict[str, Any]:
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

    def scripture(self, reference: str, abbreviation: str | None = 'kjv') -> str:
        """Return :meth:`select` output encoded as JSON."""
        return json.dumps(self.select(reference, abbreviation), ensure_ascii=False)

    def search(
        self,
        query: str,
        abbreviation: str | None = "kjv",
        criteria: SearchBible | dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """Search a translation and return additive metadata plus grouped scripture.

        ``results`` uses the same chapter-keyed object structure returned by
        :meth:`select`. ``query`` and ``matches`` add search-specific metadata
        without changing the established scripture objects.
        """
        code = self._validated_translation_code(abbreviation)
        parsed_criteria = SearchBible.from_value(criteria)
        try:
            corpus = self._search_corpus(code)
        except RepositoryResourceNotFound as error:
            raise FileNotFoundError(f"Translation ({code}) not found.") from error
        engine = SearchEngine(
            corpus,
            lambda book: self.__get.book_number(book, code),
        )
        hits, total = engine.search(query, parsed_criteria)
        return self._search_response(query, code, parsed_criteria, corpus, hits, total)

    def search_json(
        self,
        query: str,
        abbreviation: str | None = "kjv",
        criteria: SearchBible | dict[str, Any] | str | None = None,
    ) -> str:
        """Return :meth:`search` output encoded as JSON."""
        return json.dumps(
            self.search(query, abbreviation, criteria),
            ensure_ascii=False,
        )

    def valid_reference(self, reference: str, abbreviation: str | None = 'kjv') -> bool:
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

    def _validated_translation_code(self, abbreviation: str | None) -> str:
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

    def _search_corpus(self, abbreviation: str) -> TranslationCorpus:
        snapshot = self._translation_cache.load(abbreviation)
        with self._cache_guard:
            corpus = self._search_corpora.get(abbreviation)
        if corpus is not None and corpus.sha == snapshot.sha:
            corpus.refresh_state(snapshot)
            return corpus

        lock = self._resource_lock(f"translation:{abbreviation}")
        with lock:
            with self._cache_guard:
                corpus = self._search_corpora.get(abbreviation)
            if corpus is not None and corpus.sha == snapshot.sha:
                corpus.refresh_state(snapshot)
                return corpus
            corpus = TranslationCorpus(snapshot)
            with self._cache_guard:
                self._search_corpora[abbreviation] = corpus
            return corpus

    @staticmethod
    def _search_response(
        query: str,
        abbreviation: str,
        criteria: SearchBible,
        corpus: TranslationCorpus,
        hits: list[SearchHit],
        total: int,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        matches: list[dict[str, Any]] = []
        for hit in hits:
            record = hit.record
            cache_key = f"{abbreviation}_{record.book_nr}_{record.chapter}"
            if cache_key not in results:
                results[cache_key] = dict(corpus.chapter_metadata)
                results[cache_key].update(
                    {
                        "book_nr": record.book_nr,
                        "book_name": record.book_name,
                        "chapter": record.chapter,
                        "name": record.chapter_name,
                        "ref": [],
                        "verses": [],
                    }
                )
            results[cache_key]["ref"].append(record.reference)
            results[cache_key]["verses"].append(record.verse)
            matches.append(
                {
                    "reference": record.reference,
                    "book_nr": record.book_nr,
                    "chapter": record.chapter,
                    "verse": record.verse["verse"],
                    "score": hit.score,
                    "occurrences": hit.occurrences,
                    "terms": list(hit.terms),
                }
            )

        returned = len(hits)
        checked_at, stale = corpus.cache_state()
        return {
            "query": {
                "text": query,
                "criteria": criteria.to_dict(),
                "translation": corpus.translation_metadata,
                "sha": corpus.sha,
                "total": total,
                "offset": criteria.offset,
                "limit": criteria.limit,
                "returned": returned,
                "has_more": criteria.offset + returned < total,
                "cache": {
                    "checked_at": checked_at,
                    "stale": stale,
                },
            },
            "results": results,
            "matches": matches,
        }

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
