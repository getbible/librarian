"""Immutable verse records, their analysed indexes, and process-wide sharing.

Two properties matter for a service. A corpus must be built once and shared by
every caller in the process, including callers holding separate ``GetBible``
objects, because parsing a translation and analysing it is far more expensive
than answering a query. And an index build must not be charged to the request
that happened to trigger it, because abandoning a half-built index leaves
nothing cached and sends the next request down the same path.
"""

from __future__ import annotations

import threading
import time
import weakref
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any

from .._keyed_locks import KeyedLockPool
from .._memory import UNSET, estimated_bytes
from ..exceptions import CacheIntegrityError, SearchValidationError
from ..translation_cache import TranslationSnapshot
from .analysis import Analyzer, ScriptFamily, normalize_book_name
from .index import SearchIndex, build_index
from .limits import SearchLimits

__all__ = ["CorpusRegistry", "TranslationCorpus", "VerseRecord", "shared_registry"]


class VerseRecord:
    """One verse and where it sits in the translation."""

    __slots__ = ("book_name", "book_nr", "chapter", "chapter_name", "ordinal", "verse")

    def __init__(
        self,
        ordinal: int,
        book_nr: int,
        book_name: str,
        chapter: int,
        chapter_name: str,
        verse: dict[str, Any],
    ) -> None:
        self.ordinal = ordinal
        self.book_nr = book_nr
        self.book_name = book_name
        self.chapter = chapter
        self.chapter_name = chapter_name
        self.verse = verse

    @property
    def text(self) -> str:
        return str(self.verse["text"])

    @property
    def reference(self) -> str:
        return str(self.verse["name"])


class TranslationCorpus:
    """Canonical verse records with lazily built, analysed indexes."""

    _CHAPTER_METADATA = (
        "translation", "abbreviation", "lang", "language", "direction", "encoding"
    )

    def __init__(self, snapshot: TranslationSnapshot) -> None:
        self.sha = snapshot.sha
        self.checked_at = snapshot.checked_at
        self.stale = snapshot.stale
        self.translation_metadata = {
            key: value for key, value in snapshot.data.items() if key != "books"
        }
        self.chapter_metadata = {
            key: snapshot.data[key]
            for key in self._CHAPTER_METADATA
            if key in snapshot.data
        }
        self.records = self._build_records(snapshot.data)
        self.texts = tuple(record.text for record in self.records)
        self.available_books = frozenset(record.book_nr for record in self.records)
        self.book_names = self._build_book_names(self.records)
        self._indexes: dict[tuple[bool, bool], SearchIndex] = {}
        self._index_locks: dict[tuple[bool, bool], threading.Lock] = {}
        self._guard = threading.Lock()
        self._state_lock = threading.Lock()
        self._base_bytes = estimated_bytes((
            self.translation_metadata, self.chapter_metadata, self.records, self.texts,
            self.available_books, self.book_names,
        ))

    def refresh_state(self, snapshot: TranslationSnapshot) -> None:
        """Adopt freshness metadata without rebuilding unchanged indexes."""
        if snapshot.sha != self.sha:
            raise ValueError("Cannot refresh a corpus from a different translation SHA.")
        with self._state_lock:
            if snapshot.checked_at >= self.checked_at:
                self.checked_at = snapshot.checked_at
                self.stale = snapshot.stale

    def cache_state(self) -> tuple[float, bool]:
        with self._state_lock:
            return self.checked_at, self.stale

    def index(
        self,
        case_sensitive: bool = False,
        fold_diacritics: bool = True,
        limits: SearchLimits | None = None,
    ) -> SearchIndex:
        """Return the analysed view for one policy, building it at most once.

        The build runs under a per-view lock so concurrent first requests wait
        rather than each building their own copy, and the result is published
        before the lock is released so no caller repeats the work.
        """
        key = (case_sensitive, fold_diacritics)
        existing = self._indexes.get(key)
        if existing is not None:
            return existing
        with self._guard:
            lock = self._index_locks.get(key)
            if lock is None:
                lock = self._index_locks[key] = threading.Lock()
        with lock:
            existing = self._indexes.get(key)
            if existing is not None:
                return existing
            deadline = time.monotonic() + float(
                (limits or SearchLimits()).index_build_seconds
            )

            def checkpoint(ordinal: int) -> None:
                if ordinal % 4096 == 0 and time.monotonic() > deadline:
                    raise TimeoutError(
                        "Index construction exceeded its configured build window."
                    )

            built = build_index(
                self.texts,
                Analyzer(case_sensitive=case_sensitive, fold_diacritics=fold_diacritics),
                checkpoint,
            )
            with self._guard:
                self._indexes[key] = built
            return built

    @property
    def dominant_script(self) -> ScriptFamily:
        for index in self._indexes.values():
            return index.dominant_family
        return self.index().dominant_family

    @property
    def estimated_bytes(self) -> int:
        # Built views are bounded (four policies); no walk of the corpus occurs
        # on a warm request or telemetry read.
        with self._guard:
            return self._base_bytes + sum(index.estimated_bytes for index in self._indexes.values())

    def cache_info(self) -> dict[str, Any]:
        checked_at, stale = self.cache_state()
        return {
            "sha": self.sha,
            "checked_at": checked_at,
            "stale": stale,
            "verses": len(self.records),
            "estimated_bytes": self.estimated_bytes,
            "memory_measurement": "estimated_python_objects_not_rss",
            "indexes": [
                {"case_sensitive": case_sensitive, "fold_diacritics": fold}
                for case_sensitive, fold in sorted(self._indexes)
            ],
        }

    def resolve_books(
        self,
        requested: Sequence[int | str],
        fallback: Callable[[str], int | None],
    ) -> frozenset[int]:
        resolved: set[int] = set()
        for book in requested:
            number: int | None
            if isinstance(book, int):
                number = book
            elif book.strip().isdigit():
                number = int(book.strip())
            else:
                number = self.book_names.get(normalize_book_name(book))
                if number is None:
                    number = fallback(book)
            if number is None or number not in self.available_books:
                raise SearchValidationError(
                    f"Book {book!r} is not available in this translation."
                )
            resolved.add(number)
        return frozenset(resolved)

    @staticmethod
    def _build_records(data: dict[str, Any]) -> tuple[VerseRecord, ...]:
        records: list[VerseRecord] = []
        ordinal = 0
        try:
            for book in sorted(data["books"], key=lambda item: int(item["nr"])):
                book_nr = int(book["nr"])
                book_name = str(book["name"])
                chapters = sorted(book["chapters"], key=lambda item: int(item["chapter"]))
                for chapter in chapters:
                    chapter_nr = int(chapter["chapter"])
                    chapter_name = str(chapter["name"])
                    verses = sorted(chapter["verses"], key=lambda item: int(item["verse"]))
                    for verse in verses:
                        if not all(key in verse for key in ("chapter", "verse", "name", "text")):
                            raise KeyError("verse")
                        records.append(
                            VerseRecord(
                                ordinal=ordinal,
                                book_nr=book_nr,
                                book_name=book_name,
                                chapter=chapter_nr,
                                chapter_name=chapter_name,
                                verse=dict(verse),
                            )
                        )
                        ordinal += 1
        except (KeyError, TypeError, ValueError) as error:
            raise CacheIntegrityError(
                "Translation contains invalid book or verse data."
            ) from error
        return tuple(records)

    @staticmethod
    def _build_book_names(records: Sequence[VerseRecord]) -> dict[str, int]:
        return {
            normalize_book_name(record.book_name): record.book_nr for record in records
        }


class CorpusRegistry:
    """Bounded, process-wide corpora keyed by repository, translation and SHA.

    Sharing is keyed on the source SHA, so a translation that changes upstream
    produces a new entry rather than silently reusing stale verses. Separate
    ``GetBible`` objects in one process reach the same corpus, which is what
    stops a service paying the parse-and-analyse cost per client object.
    """

    def __init__(self, limit: int = 8, memory_bytes: int | None = None) -> None:
        self._entries: OrderedDict[tuple[str, str, str], TranslationCorpus] = OrderedDict()
        self._live: weakref.WeakValueDictionary[tuple[str, str, str], TranslationCorpus] = (
            weakref.WeakValueDictionary()
        )
        self._limit = self._validated_limit("limit", limit, nullable=False)
        self._memory_bytes = self._validated_limit("memory_bytes", memory_bytes)
        self._lock = threading.Lock()
        self._build_locks = KeyedLockPool()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def acquire(
        self, repository: str, abbreviation: str, snapshot: TranslationSnapshot,
    ) -> TranslationCorpus:
        key = (repository, abbreviation, snapshot.sha)
        # Serializing one key prevents simultaneous first callers from parsing
        # duplicate corpora. Unrelated translations can still load concurrently.
        with self._build_locks.hold(key):
            with self._lock:
                corpus = self._live.get(key)
                if corpus is not None:
                    self.hits += 1
                    corpus.refresh_state(snapshot)
                    already_retained = key in self._entries
                    self._entries[key] = corpus
                    self._entries.move_to_end(key)
                    if not already_retained:
                        self._trim()
                    return corpus
                self.misses += 1
            corpus = TranslationCorpus(snapshot)
            with self._lock:
                self._live[key] = corpus
                self._entries[key] = corpus
                # Retain only the current SHA strongly. In-flight searches hold
                # their immutable previous corpus until they finish naturally.
                for previous in list(self._entries):
                    if previous[:2] == key[:2] and previous != key:
                        del self._entries[previous]
                self._trim()
            return corpus

    def resize(self, limit: int, *, memory_bytes: Any = UNSET) -> None:
        """Configure process-wide strong retention; zero disables retention."""
        limit = self._validated_limit("limit", limit, nullable=False)
        if memory_bytes is not UNSET:
            self._validated_limit("memory_bytes", memory_bytes)
        with self._lock:
            self._limit = limit
            if memory_bytes is not UNSET:
                self._memory_bytes = memory_bytes
            self._trim()

    def enforce_budget(self) -> None:
        """Recheck capacity after a new lazy index has been built."""
        with self._lock:
            self._trim()

    def _trim(self) -> None:
        total = sum(corpus.estimated_bytes for corpus in self._entries.values())
        while self._entries and (
            len(self._entries) > self._limit
            or (self._memory_bytes is not None and total > self._memory_bytes)
        ):
            _, corpus = self._entries.popitem(last=False)
            total -= corpus.estimated_bytes
            self.evictions += 1

    def discard(self, repository: str, abbreviation: str | None = None) -> None:
        with self._lock:
            for key in list(self._live):
                if key[0] == repository and (abbreviation is None or key[1] == abbreviation):
                    self._entries.pop(key, None)
                    self._live.pop(key, None)

    def info(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "limit": self._limit,
                "memory_bytes_limit": self._memory_bytes,
                "estimated_bytes": sum(corpus.estimated_bytes for corpus in self._entries.values()),
                "memory_measurement": "estimated_python_objects_not_rss",
                "active_or_client_retained_entries": len(self._live),
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "active_build_locks": self._build_locks.size,
            }

    @staticmethod
    def _validated_limit(name: str, value: Any, *, nullable: bool = True) -> Any:
        if value is None and nullable:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            suffix = " or null." if nullable else "."
            raise ValueError(f"{name} must be a non-negative integer" + suffix)
        return value


_SHARED = CorpusRegistry()


def shared_registry() -> CorpusRegistry:
    """Return the registry every ``GetBible`` in this process shares."""
    return _SHARED

