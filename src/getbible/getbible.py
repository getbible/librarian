"""Public Librarian facade for reference-based scripture selection."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ._keyed_locks import KeyedLockPool
from ._memory import UNSET, estimated_bytes
from .exceptions import (
    CacheIntegrityError,
    RepositoryResourceNotFound,
    RepositoryResponseError,
    SearchLimitError,
)
from .getbible_reference import BookReference, GetBibleReference
from .repository_client import RepositoryClient
from .search import (
    SearchBible,
    SearchEngine,
    SearchHit,
    SearchLimits,
    TranslationCorpus,
    shared_registry,
)
from .source_generation import PurgeCallback, SourceCoordinator, SourceGeneration
from .translation_cache import TranslationCache


@dataclass
class _CacheEntry:
    data: dict[str, Any]
    loaded_at: float
    sha: str | None = None
    estimated_bytes: int = 0


@dataclass(slots=True)
class _CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
        }


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
        reference_cache_limit: int | None = 5000,
        books_cache_limit: int | None = 64,
        chapter_cache_limit: int | None = 2048,
        search_corpus_limit: int | None = 4,
        translation_cache_limit: int | None = 4,
        cache_ttl_jitter: float = 0.1,
        require_checksums: bool | None = None,
        source_purge_callback: PurgeCallback | None = None,
        search_limits: SearchLimits | None = None,
        shared_corpus_limit: int | None = None,
        shared_corpus_bytes: int | None = None,
        chapter_cache_bytes: int | None = None,
        translation_cache_bytes: int | None = None,
    ) -> None:
        reference_cache_limit = self._validated_cache_limit(
            "reference_cache_limit", reference_cache_limit
        )
        self._books_cache_limit = self._validated_cache_limit(
            "books_cache_limit", books_cache_limit
        )
        self._chapter_cache_limit = self._validated_cache_limit(
            "chapter_cache_limit", chapter_cache_limit
        )
        self._search_corpus_limit = self._validated_cache_limit(
            "search_corpus_limit", search_corpus_limit
        )
        translation_cache_limit = self._validated_cache_limit(
            "translation_cache_limit", translation_cache_limit
        )
        self._chapter_cache_bytes = self._validated_cache_limit(
            "chapter_cache_bytes", chapter_cache_bytes
        )
        self._shared_corpus_bytes = self._validated_cache_limit(
            "shared_corpus_bytes", shared_corpus_bytes
        )
        shared_corpus_limit = self._validated_cache_limit(
            "shared_corpus_limit", shared_corpus_limit
        )
        self.__get = GetBibleReference(cache_limit=reference_cache_limit)
        self._repository = RepositoryClient(
            repo_path=repo_path,
            version=version,
            timeout=request_timeout,
            retries=request_retries,
        )
        if require_checksums is not None and not isinstance(require_checksums, bool):
            raise TypeError("require_checksums must be a boolean or null.")
        self._require_checksums = (
            self._repository.is_url if require_checksums is None else require_checksums
        )
        if search_limits is not None and not isinstance(search_limits, SearchLimits):
            raise TypeError("search_limits must be a SearchLimits object or null.")
        self.search_limits = search_limits or SearchLimits()
        self._cache_ttl_seconds = self._validated_ttl(cache_ttl)
        self.__books_cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self.__chapters_cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._chapter_bytes = 0
        self._cache_guard = threading.RLock()
        self._resource_locks = KeyedLockPool()
        self._cache_stats = {
            "books": _CacheStats(),
            "chapters": _CacheStats(),
            "search_corpora": _CacheStats(),
        }
        self._translation_cache = TranslationCache(
            repository=self._repository,
            refresh_seconds=self._cache_ttl_seconds,
            cache_dir=cache_dir,
            strict_freshness=strict_freshness,
            memory_limit=translation_cache_limit,
            memory_bytes=translation_cache_bytes,
            refresh_jitter=cache_ttl_jitter,
            require_checksums=self._require_checksums,
        )
        self._search_corpora: OrderedDict[str, TranslationCorpus] = OrderedDict()
        # Corpora are shared process-wide, keyed by the repository they came
        # from so two clients pointed at different repositories never collide.
        self._repository_key = f"{self._repository.repo_path}/{self._repository.version}"
        self._corpus_registry = shared_registry()
        if shared_corpus_limit is not None or shared_corpus_bytes is not None:
            self._corpus_registry.resize(
                (self._corpus_registry.info()["limit"]
                 if shared_corpus_limit is None else shared_corpus_limit),
                memory_bytes=shared_corpus_bytes,
            )
        self._source_coordinator = SourceCoordinator(
            cache_root=self._translation_cache.cache_dir,
            source=self._repository.repo_path,
            version=self._repository.version,
            invalidate_callback=self._invalidate_worker_caches,
            purge_callback=source_purge_callback,
        )
        initial_generation = self._source_coordinator.info()["generation"]
        self._translation_cache.set_source_generation(int(initial_generation))

    def select(self, reference: str, abbreviation: str | None = 'kjv') -> dict[str, Any]:
        """Return Bible verses using the established grouped result contract."""
        with self.source_operation():
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
        with self.source_operation():
            code = self._validated_translation_code(abbreviation)
            parsed_criteria = SearchBible.from_value(criteria)
            try:
                corpus = self._search_corpus(code)
            except RepositoryResourceNotFound as error:
                raise FileNotFoundError(f"Translation ({code}) not found.") from error
            engine = SearchEngine(
                corpus,
                lambda book: self.__get.book_number(book, code),
                self.search_limits,
            )
            size_before = corpus.estimated_bytes
            try:
                hits, total = engine.search(query, parsed_criteria)
            finally:
                if corpus.estimated_bytes != size_before:
                    self._enforce_corpus_budgets()
            return self._search_response(
                query,
                code,
                parsed_criteria,
                corpus,
                hits,
                total,
                engine.execution_info,
                self.search_limits.max_response_bytes,
            )

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

    def warm_translation(
        self,
        abbreviation: str | None = "kjv",
        *,
        case_sensitive: bool = False,
        diacritics: str = "fold",
    ) -> dict[str, Any]:
        """Load one translation corpus and analysed index before traffic.

        This method performs no artificial query and returns operational metadata
        only. Call it before a pre-fork server creates workers when copy-on-write
        sharing is desired.
        """
        with self.source_operation():
            code = self._validated_translation_code(abbreviation)
            criteria = SearchBible(
                case_sensitive=case_sensitive,
                diacritics=diacritics,
                limit=1,
            )
            try:
                corpus = self._search_corpus(code)
            except RepositoryResourceNotFound as error:
                raise FileNotFoundError(f"Translation ({code}) not found.") from error
            size_before = corpus.estimated_bytes
            try:
                index = corpus.index(
                    criteria.case_sensitive, criteria.fold_diacritics, self.search_limits
                )
            finally:
                if corpus.estimated_bytes != size_before:
                    self._enforce_corpus_budgets()
            return {
                "abbreviation": code,
                **corpus.cache_info(),
                "analysis": index.analysis_report(),
            }

    def warm_query(
        self, abbreviation: str | None = "kjv", *, references: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Explicitly warm reference chapters, without building a search index.

        ``references`` loads just the selected chapters through the normal
        lightweight path. Omitting it explicitly requests all chapters from a
        checksum-validated full snapshot. Ordinary ``select`` never does that.
        Capacity settings can retain fewer chapters than this call loaded.
        """
        code = self._validated_translation_code(abbreviation)
        if references is not None and (
            isinstance(references, (str, bytes)) or not isinstance(references, Sequence)
            or not all(isinstance(item, str) for item in references)
        ):
            raise TypeError("references must be a sequence of reference strings or null.")
        with self.source_operation():
            self.__check_translation(code)
            loaded = 0
            stale = False
            if references is not None:
                for reference in references:
                    self.select(reference, code)
                    loaded += 1
            else:
                snapshot = self._translation_cache.load(code)
                stale = snapshot.stale
                loaded_at = time.monotonic() - max(0.0, time.time() - snapshot.checked_at)
                metadata = {
                    key: value for key, value in snapshot.data.items() if key != "books"
                }
                for book in snapshot.data["books"]:
                    for chapter in book["chapters"]:
                        payload = {
                            **metadata, "book_nr": book["nr"], "book_name": book["name"],
                            "chapter": chapter["chapter"], "name": chapter["name"],
                            "verses": {str(verse["verse"]): verse for verse in chapter["verses"]},
                        }
                        key = f"{code}_{book['nr']}_{chapter['chapter']}"
                        with self._resource_locks.hold(f"chapter:{key}"), self._cache_guard:
                            self._put_bounded(
                                self.__chapters_cache, key, _CacheEntry(payload, loaded_at),
                                self._chapter_cache_limit, "chapters",
                            )
                        loaded += 1
            info = self.cache_info()
            return {
                "abbreviation": code, "target": "query", "loaded": loaded, "stale": stale,
                "source_generation": info["source"]["generation"],
                **info["query_translations"].get(code, {"chapters": 0, "estimated_bytes": 0}),
            }

    def configure_cache(
        self, *, cache_ttl: timedelta | None = None, cache_ttl_jitter: float | None = None,
        books_cache_limit: Any = UNSET, chapter_cache_limit: Any = UNSET,
        search_corpus_limit: Any = UNSET, translation_cache_limit: Any = UNSET,
        shared_corpus_limit: Any = UNSET, shared_corpus_bytes: Any = UNSET,
        chapter_cache_bytes: Any = UNSET, translation_cache_bytes: Any = UNSET,
    ) -> dict[str, Any]:
        """Validate and apply cache limits without resetting freshness or data.

        Omitted settings remain unchanged. ``None`` removes an optional count
        or byte limit; ``0`` disables retention. The shared registry count must
        remain an integer because it bounds process-wide retention.
        """
        values = {
            "books_cache_limit": books_cache_limit, "chapter_cache_limit": chapter_cache_limit,
            "search_corpus_limit": search_corpus_limit,
            "translation_cache_limit": translation_cache_limit,
            "shared_corpus_limit": shared_corpus_limit, "shared_corpus_bytes": shared_corpus_bytes,
            "chapter_cache_bytes": chapter_cache_bytes,
            "translation_cache_bytes": translation_cache_bytes,
        }
        for name, value in values.items():
            if value is not UNSET:
                self._validated_cache_limit(name, value)
        if shared_corpus_limit is None:
            raise ValueError("shared_corpus_limit must be a non-negative integer.")
        seconds = self._validated_ttl(cache_ttl) if cache_ttl is not None else None
        if cache_ttl_jitter is not None and (
            not isinstance(cache_ttl_jitter, (int, float)) or isinstance(cache_ttl_jitter, bool)
            or not 0 <= cache_ttl_jitter < 1
        ):
            raise ValueError("cache_ttl_jitter must be between 0 (inclusive) and 1.")
        with self._source_coordinator.cache_maintenance():
            self._translation_cache.configure(
                refresh_seconds=seconds, refresh_jitter=cache_ttl_jitter,
                memory_limit=translation_cache_limit, memory_bytes=translation_cache_bytes,
            )
            with self._cache_guard:
                if seconds is not None:
                    self._cache_ttl_seconds = seconds
                for name in ("books_cache_limit", "chapter_cache_limit", "search_corpus_limit",
                             "chapter_cache_bytes", "shared_corpus_bytes"):
                    if values[name] is not UNSET:
                        setattr(self, "_" + name, values[name])
                self._trim_chapter_books()
            if shared_corpus_limit is not UNSET or shared_corpus_bytes is not UNSET:
                self._corpus_registry.resize(
                    (self._corpus_registry.info()["limit"]
                     if shared_corpus_limit is UNSET else shared_corpus_limit),
                    memory_bytes=shared_corpus_bytes,
                )
            self._enforce_corpus_budgets()
            return self.cache_info()

    def drop_translation(self, abbreviation: str, *, disk: bool = False) -> dict[str, Any]:
        """Drop this client's resident translation and its shared registry entry.

        Does not cancel in-flight operations. Other worker processes must receive
        their own command. ``disk=True`` also deletes Librarian-owned cache
        objects and metadata, never files belonging to the source repository.
        """
        code = self._validated_translation_code(abbreviation)
        if not isinstance(disk, bool):
            raise TypeError("disk must be a boolean.")
        with self._source_coordinator.cache_maintenance():
            self._drop_translation(code, disk=disk)
            return {"abbreviation": code, "dropped": True, "disk": disk, "scope": "client"}

    def _drop_translation(self, code: str, *, disk: bool = False) -> None:
        with self._cache_guard:
            self.__books_cache.pop(code, None)
            for key in list(self.__chapters_cache):
                if key.rsplit("_", 2)[0] == code:
                    self._chapter_bytes -= self.__chapters_cache.pop(key).estimated_bytes
            self._search_corpora.pop(code, None)
        self._translation_cache.drop(code, disk=disk)
        self._corpus_registry.discard(self._repository_key, code)
        self._on_translation_dropped(code)

    def _on_translation_dropped(self, abbreviation: str) -> None:
        """Subclass hook for availability/result-cache invalidation."""

    def reload_translation(
        self, abbreviation: str, *, target: str = "search", references: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Force source verification and rebuild requested resident views.

        The old validated disk cache remains available for configured stale
        fallback. A successful reload is not reported as fresh when fallback
        was necessary; search metadata exposes ``stale``.
        """
        code = self._validated_translation_code(abbreviation)
        if target not in {"search", "query", "both"}:
            raise ValueError("target must be search, query or both.")
        if references is not None and (
            isinstance(references, (str, bytes)) or not isinstance(references, Sequence)
            or not all(isinstance(item, str) for item in references)
        ):
            raise TypeError("references must be a sequence of reference strings or null.")
        with self._source_coordinator.cache_maintenance():
            # Validate a replacement before dropping the last good resident
            # corpus. Force bypasses freshness, retaining checksum protection.
            snapshot = self._translation_cache.load(code, force=True)
            self._drop_translation(code)
            self._translation_cache._remember(code, snapshot)
            result: dict[str, Any] = {"abbreviation": code, "target": target}
            if target in {"search", "both"}:
                result["search"] = self.warm_translation(code)
            if target in {"query", "both"}:
                result["query"] = self.warm_query(code, references=references)
            return result

    def _enforce_corpus_budgets(self) -> None:
        with self._cache_guard:
            while self._search_corpora and (
                (self._search_corpus_limit is not None and
                 len(self._search_corpora) > self._search_corpus_limit)
                or (self._shared_corpus_bytes is not None and
                    sum(corpus.estimated_bytes for corpus in self._search_corpora.values())
                    > self._shared_corpus_bytes)
            ):
                self._search_corpora.popitem(last=False)
                self._cache_stats["search_corpora"].evictions += 1
        self._corpus_registry.enforce_budget()

    def _trim_chapter_books(self) -> None:
        for cache, limit, category in (
            (self.__books_cache, self._books_cache_limit, "books"),
            (self.__chapters_cache, self._chapter_cache_limit, "chapters"),
        ):
            while cache and (
                (limit is not None and len(cache) > limit)
                or (category == "chapters" and self._chapter_cache_bytes is not None and
                    self._chapter_bytes > self._chapter_cache_bytes)
            ):
                _, removed = cache.popitem(last=False)
                if category == "chapters":
                    self._chapter_bytes -= removed.estimated_bytes
                self._cache_stats[category].evictions += 1

    @staticmethod
    def _validated_ttl(value: timedelta) -> float:
        if not isinstance(value, timedelta):
            raise TypeError("cache_ttl must be a timedelta.")
        seconds = value.total_seconds()
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("cache_ttl must be finite and non-negative.")
        return seconds

    def cache_info(self) -> dict[str, Any]:
        """Return bounded-cache state and counters without exposing payloads."""
        with self.source_operation(), self._cache_guard:
            corpora = {
                code: corpus.cache_info()
                for code, corpus in self._search_corpora.items()
            }
            books = self._cache_summary(
                len(self.__books_cache), self._books_cache_limit, "books"
            )
            chapters = self._cache_summary(
                len(self.__chapters_cache), self._chapter_cache_limit, "chapters"
            )
            search_corpora = self._cache_summary(
                len(self._search_corpora),
                self._search_corpus_limit,
                "search_corpora",
            )
            query_translations: dict[str, Any] = {}
            now = time.monotonic()
            for key, entry in self.__chapters_cache.items():
                code = key.rsplit("_", 2)[0]
                state = query_translations.setdefault(code, {
                    "chapters": 0, "estimated_bytes": 0, "expired_chapters": 0,
                })
                state["chapters"] += 1
                state["estimated_bytes"] += entry.estimated_bytes
                state["expired_chapters"] += int(now - entry.loaded_at >= self._cache_ttl_seconds)
            chapters["estimated_bytes"] = self._chapter_bytes
            chapters["memory_bytes_limit"] = self._chapter_cache_bytes
        search_corpora["translations"] = corpora
        return {
            "ttl_seconds": self._cache_ttl_seconds,
            "freshness_policy": "lazy_revalidate_retain_unchanged_sha",
            "memory_measurement": "estimated_python_objects_not_rss",
            "query_translations": query_translations,
            "shared_registry": self._corpus_registry.info(),
            "references": self.__get.cache_info(),
            "books": books,
            "chapters": chapters,
            "search_corpora": search_corpora,
            "translation_cache": self._translation_cache.cache_info(),
            "active_resource_locks": self._resource_locks.size,
            "source": self._source_coordinator.info(),
        }

    @contextmanager
    def source_operation(self) -> Iterator[SourceGeneration]:
        """Hold one source generation across an external cache transaction."""
        with self._source_coordinator.source_operation() as generation:
            yield generation

    def transition_source(
        self,
        revision: str,
        purge_callback: PurgeCallback | None = None,
    ) -> dict[str, str | int | float]:
        """Activate an immutable mirror revision and invalidate every worker cache."""
        return self._source_coordinator.transition(revision, purge_callback).to_dict()

    def close(self) -> None:
        """Close repository HTTP sessions during application shutdown."""
        self._repository.close()

    def __enter__(self) -> GetBible:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

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
        with self.source_operation(), self._resource_locks.hold(key):
            with self._cache_guard:
                entry = self.__books_cache.get(code)
            if entry is not None and self._is_fresh(entry):
                with self._cache_guard:
                    if self.__books_cache.get(code) is entry:
                        self.__books_cache.move_to_end(code)
                    self._cache_stats["books"].hits += 1
                return True
            with self._cache_guard:
                self._cache_stats["books"].misses += 1
            try:
                books = self._repository.fetch_json(f"{code}/books.json")
            except RepositoryResourceNotFound:
                return False
            with self._cache_guard:
                self._put_bounded(
                    self.__books_cache,
                    code,
                    _CacheEntry(books, time.monotonic()),
                    self._books_cache_limit,
                    "books",
                )
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

    def _is_fresh(self, entry: _CacheEntry) -> bool:
        return time.monotonic() - entry.loaded_at < self._cache_ttl_seconds

    def _search_corpus(self, abbreviation: str) -> TranslationCorpus:
        """Return the corpus for one translation, shared across this process.

        Corpora live in a registry keyed by repository, translation and source
        SHA rather than on this object, so two ``GetBible`` instances in one
        process reach the same parsed verses and the same analysed indexes. A
        service therefore pays the parse-and-analyse cost once per translation
        version, not once per client object.
        """
        snapshot = self._translation_cache.load(abbreviation)
        registry = self._corpus_registry
        before = registry.misses
        with self._resource_locks.hold(f"translation:{abbreviation}"):
            corpus = registry.acquire(self._repository_key, abbreviation, snapshot)
        with self._cache_guard:
            counters = self._cache_stats["search_corpora"]
            if registry.misses == before:
                counters.hits += 1
            else:
                counters.misses += 1
            changed = self._search_corpora.get(abbreviation) is not corpus
            self._search_corpora[abbreviation] = corpus
            self._search_corpora.move_to_end(abbreviation)
            while (
                self._search_corpus_limit is not None
                and len(self._search_corpora) > self._search_corpus_limit
            ):
                self._search_corpora.popitem(last=False)
                counters.evictions += 1
        if changed:
            self._enforce_corpus_budgets()
        return corpus

    @staticmethod
    def _search_response(
        query: str,
        abbreviation: str,
        criteria: SearchBible,
        corpus: TranslationCorpus,
        hits: list[SearchHit],
        total: int,
        execution_info: dict[str, int | float | bool],
        max_response_bytes: int,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        matches: list[dict[str, Any]] = []
        accumulated_bytes = GetBible._json_bytes(corpus.translation_metadata)
        if accumulated_bytes > max_response_bytes:
            raise SearchLimitError(
                "Search translation metadata exceeds the configured response-volume budget."
            )
        for hit in hits:
            record = hit.record
            cache_key = f"{abbreviation}_{record.book_nr}_{record.chapter}"
            if cache_key not in results:
                results[cache_key] = deepcopy(corpus.chapter_metadata)
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
                accumulated_bytes += GetBible._json_bytes(results[cache_key])
            results[cache_key]["ref"].append(record.reference)
            verse = deepcopy(record.verse)
            match = {
                "reference": record.reference,
                "book_nr": record.book_nr,
                "chapter": record.chapter,
                "verse": record.verse["verse"],
                "score": hit.score,
                "occurrences": hit.occurrences,
                "terms": list(hit.terms),
            }
            accumulated_bytes += GetBible._json_bytes(verse)
            accumulated_bytes += GetBible._json_bytes(match)
            if accumulated_bytes > max_response_bytes:
                raise SearchLimitError(
                    "Search results exceed the configured response-volume budget."
                )
            results[cache_key]["verses"].append(verse)
            matches.append(match)

        returned = len(hits)
        checked_at, stale = corpus.cache_state()
        response = {
            "query": {
                "text": query,
                "criteria": criteria.to_dict(),
                "engine_version": execution_info["engine_version"],
                "translation": deepcopy(corpus.translation_metadata),
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
                # How this translation was read. Exposed so an application can
                # see the engine's choice rather than having to make it.
                "analysis": {"script": execution_info["script"]},
                "cost": {
                    "work_units": execution_info["work_units"],
                    "deadline_seconds": execution_info["deadline_seconds"],
                    "expensive": execution_info["expensive"],
                },
            },
            "results": results,
            "matches": matches,
        }
        response_bytes = len(
            json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if response_bytes > max_response_bytes:
            raise SearchLimitError(
                f"Search response requires {response_bytes} bytes; the configured maximum "
                f"is {max_response_bytes}."
            )
        return response

    @staticmethod
    def _json_bytes(value: Any) -> int:
        return len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )

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
                    result[cache_key]["verses"].append(deepcopy(verse_info))
                if book_ref.reference not in result[cache_key]["ref"]:
                    result[cache_key]["ref"].append(book_ref.reference)
                continue

            result[cache_key] = {
                key: deepcopy(value)
                for key, value in chapter_data.items()
                if key != "verses"
            }
            result[cache_key]["ref"] = [book_ref.reference]
            result[cache_key]["verses"] = [deepcopy(verse_info)]

    def _chapter(self, abbreviation: str, book: int, chapter: int) -> dict[str, Any]:
        cache_key = f"{abbreviation}_{book}_{chapter}"
        with self._resource_locks.hold(f"chapter:{cache_key}"):
            with self._cache_guard:
                entry = self.__chapters_cache.get(cache_key)
            if entry is not None and self._is_fresh(entry):
                with self._cache_guard:
                    if self.__chapters_cache.get(cache_key) is entry:
                        self.__chapters_cache.move_to_end(cache_key)
                    self._cache_stats["chapters"].hits += 1
                return entry.data

            with self._cache_guard:
                self._cache_stats["chapters"].misses += 1

            checksum_path = f"{abbreviation}/{book}/{chapter}.sha"
            remote_sha = self._published_checksum(
                checksum_path,
                f"chapter {abbreviation} {book}:{chapter}",
            )
            if entry is not None and entry.sha and remote_sha == entry.sha:
                entry.loaded_at = time.monotonic()
                with self._cache_guard:
                    if self.__chapters_cache.get(cache_key) is entry:
                        self.__chapters_cache.move_to_end(cache_key)
                return entry.data

            relative_path = f"{abbreviation}/{book}/{chapter}.json"
            try:
                raw = self._repository.fetch_bytes(relative_path)
            except RepositoryResourceNotFound as error:
                raise FileNotFoundError(
                    f"Chapter:{chapter} in book:{book} for {abbreviation} not found."
                ) from error
            if self._require_checksums and not remote_sha:
                raise RepositoryResponseError(
                    f"Chapter {abbreviation} {book}:{chapter} has no required checksum."
                )
            try:
                chapter_data = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CacheIntegrityError(
                    f"Invalid chapter JSON for {abbreviation} {book}:{chapter}."
                ) from error
            actual_sha = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
            if remote_sha and actual_sha != remote_sha:
                raise CacheIntegrityError(
                    f"Checksum mismatch for chapter {abbreviation} {book}:{chapter}: "
                    f"expected {remote_sha}, received {actual_sha}."
                )
            TranslationCache.validate_chapter_payload(
                chapter_data,
                abbreviation,
                book,
                chapter,
            )

            chapter_data["verses"] = {
                str(verse["verse"]): verse for verse in chapter_data["verses"]
            }
            loaded = _CacheEntry(
                data=chapter_data,
                loaded_at=time.monotonic(),
                sha=actual_sha,
            )
            with self._cache_guard:
                self._put_bounded(
                    self.__chapters_cache,
                    cache_key,
                    loaded,
                    self._chapter_cache_limit,
                    "chapters",
                )
            return chapter_data

    def _published_checksum(self, relative_path: str, label: str) -> str:
        try:
            checksum = self._repository.fetch_text(relative_path).strip().lower()
        except RepositoryResourceNotFound:
            return ""
        if not TranslationCache._valid_sha(checksum):
            raise RepositoryResponseError(f"{label.capitalize()} publishes an invalid checksum.")
        return checksum

    def _invalidate_worker_caches(self, generation: SourceGeneration) -> None:
        with self._cache_guard:
            self.__books_cache.clear()
            self.__chapters_cache.clear()
            self._chapter_bytes = 0
            self._search_corpora.clear()
        self._corpus_registry.discard(self._repository_key)
        self._translation_cache.set_source_generation(generation.generation)
        self._on_source_generation_changed(generation)

    def _on_source_generation_changed(self, generation: SourceGeneration) -> None:
        """Allow hardened subclasses to invalidate additional process-local state."""

    def __check_translation(self, abbreviation: str) -> None:
        if not self.valid_translation(abbreviation):
            raise FileNotFoundError(f"Translation ({abbreviation}) not found.")

    def _put_bounded(
        self,
        cache: OrderedDict[str, Any],
        key: str,
        value: Any,
        limit: int | None,
        category: str,
    ) -> None:
        previous = cache.pop(key, None)
        if category == "chapters" and previous is not None:
            self._chapter_bytes -= previous.estimated_bytes
        if limit == 0:
            return
        value.estimated_bytes = estimated_bytes(value.data)
        if (
            category == "chapters" and self._chapter_cache_bytes is not None
            and value.estimated_bytes > self._chapter_cache_bytes
        ):
            self._cache_stats[category].evictions += 1
            return
        cache[key] = value
        if category == "chapters":
            self._chapter_bytes += value.estimated_bytes
        self._trim_chapter_books()

    def _cache_summary(
        self,
        size: int,
        limit: int | None,
        category: str,
    ) -> dict[str, Any]:
        return {
            "size": size,
            "limit": limit,
            **self._cache_stats[category].to_dict(),
        }

    @staticmethod
    def _validated_cache_limit(name: str, value: int | None) -> int | None:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an integer or null.")
        if value < 0:
            raise ValueError(f"{name} cannot be negative.")
        return value

