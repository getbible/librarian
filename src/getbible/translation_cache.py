"""Persistent, checksum-validated full-translation caching."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import tempfile
import threading
import time
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filelock import FileLock

from ._keyed_locks import KeyedLockPool
from .exceptions import (
    CacheIntegrityError,
    RepositoryError,
    RepositoryResourceNotFound,
    RepositoryResponseError,
)
from .repository_client import RepositoryClient

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TranslationSnapshot:
    """A validated full translation and its source state."""

    data: dict[str, Any]
    sha: str
    checked_at: float
    stale: bool = False


@dataclass(frozen=True, slots=True)
class _CacheMetadata:
    sha: str
    checked_at: float
    payload: str
    books_sha: str
    source_generation: int


@dataclass(frozen=True, slots=True)
class _BookIndexEntry:
    name: str
    metadata: tuple[tuple[str, str], ...]


class TranslationCache:
    """Coordinate in-memory and cross-process on-disk translation caching."""

    VALIDATION_VERSION = 2
    MAX_BOOKS = 256
    MAX_CHAPTERS_PER_BOOK = 500
    MAX_VERSES_PER_CHAPTER = 500
    MAX_TOTAL_VERSES = 100_000
    MAX_BOOK_NUMBER = 1_000
    MAX_CHAPTER_NUMBER = 1_000
    MAX_VERSE_NUMBER = 2_000
    MAX_NAME_LENGTH = 4_096
    MAX_TEXT_LENGTH = 1_048_576
    MAX_METADATA_ITEMS = 10_000
    MAX_METADATA_DEPTH = 8
    MAX_METADATA_INTEGER = (1 << 63) - 1
    BOOK_INDEX_METADATA = (
        "translation",
        "abbreviation",
        "lang",
        "language",
        "direction",
        "encoding",
    )

    def __init__(
        self,
        repository: RepositoryClient,
        refresh_seconds: float,
        cache_dir: str | os.PathLike[str] | None = None,
        strict_freshness: bool = False,
        lock_timeout: float = 120.0,
        memory_limit: int | None = 4,
        refresh_jitter: float = 0.1,
        require_checksums: bool = False,
    ) -> None:
        self.repository = repository
        self.refresh_seconds = max(0.0, refresh_seconds)
        self.cache_dir = self._cache_root(cache_dir)
        self.strict_freshness = strict_freshness
        self.lock_timeout = lock_timeout
        self.memory_limit = self._validated_limit("memory_limit", memory_limit)
        if not isinstance(require_checksums, bool):
            raise TypeError("require_checksums must be a boolean.")
        self.require_checksums = require_checksums
        if not isinstance(refresh_jitter, (int, float)) or isinstance(
            refresh_jitter, bool
        ):
            raise TypeError("refresh_jitter must be a number.")
        if not 0 <= refresh_jitter < 1:
            raise ValueError("refresh_jitter must be between 0 (inclusive) and 1.")
        self.refresh_jitter = float(refresh_jitter)
        self._memory: OrderedDict[str, TranslationSnapshot] = OrderedDict()
        self._source_generation = 0
        self._locks = KeyedLockPool()
        self._guard = threading.RLock()
        self._stats = {
            "memory_hits": 0,
            "disk_hits": 0,
            "source_checks": 0,
            "downloads": 0,
            "stale_fallbacks": 0,
            "evictions": 0,
        }

    def load(self, abbreviation: str) -> TranslationSnapshot:
        """Return a fresh or last-known-good translation snapshot."""
        now = time.time()
        with self._guard:
            memory = self._memory.get(abbreviation)
            if memory is not None:
                self._memory.move_to_end(abbreviation)
        if memory is not None and self._is_fresh(abbreviation, memory, now):
            self._increment("memory_hits")
            return memory

        with self._locks.hold(abbreviation):
            now = time.time()
            with self._guard:
                memory = self._memory.get(abbreviation)
                if memory is not None:
                    self._memory.move_to_end(abbreviation)
            if memory is not None and self._is_fresh(abbreviation, memory, now):
                self._increment("memory_hits")
                return memory

            paths = self._paths(abbreviation)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            with FileLock(str(paths["lock"]), timeout=self.lock_timeout):
                metadata = self._read_metadata(paths)
                disk = None
                if (
                    memory is not None
                    and metadata is not None
                    and metadata.sha == memory.sha
                ):
                    disk = TranslationSnapshot(
                        memory.data,
                        memory.sha,
                        metadata.checked_at,
                    )
                else:
                    disk = self._read_disk(paths, metadata)
                if disk is None and memory is not None:
                    disk = memory
                if disk is not None and self._is_fresh(abbreviation, disk, now):
                    self._increment("disk_hits")
                    return self._remember(abbreviation, disk)

                try:
                    self._increment("source_checks")
                    refreshed = self._refresh(abbreviation, paths, disk, now)
                except RepositoryResourceNotFound:
                    if disk is None:
                        raise
                    if self.strict_freshness:
                        raise
                    LOGGER.warning(
                        "Serving stale translation %s because its source is unavailable.",
                        abbreviation,
                    )
                    self._increment("stale_fallbacks")
                    refreshed = TranslationSnapshot(
                        disk.data, disk.sha, disk.checked_at, stale=True
                    )
                except (CacheIntegrityError, RepositoryError):
                    if disk is None or self.strict_freshness:
                        raise
                    LOGGER.warning(
                        "Serving stale translation %s after a repository failure.",
                        abbreviation,
                        exc_info=True,
                    )
                    self._increment("stale_fallbacks")
                    refreshed = TranslationSnapshot(
                        disk.data, disk.sha, disk.checked_at, stale=True
                    )
                return self._remember(abbreviation, refreshed)

    def invalidate(self, abbreviation: str | None = None) -> None:
        """Evict one or every in-memory translation snapshot."""
        with self._guard:
            if abbreviation is None:
                self._memory.clear()
            else:
                self._memory.pop(abbreviation, None)

    def set_source_generation(self, generation: int) -> None:
        """Expire retained state after an immutable source transition."""
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
            raise ValueError("source generation must be a non-negative integer.")
        with self._guard:
            if generation != self._source_generation:
                self._source_generation = generation
                self._memory.clear()

    def cache_info(self) -> dict[str, Any]:
        """Return a JSON-friendly snapshot of translation-cache state."""
        with self._guard:
            translations = {
                code: {
                    "sha": snapshot.sha,
                    "checked_at": snapshot.checked_at,
                    "stale": snapshot.stale,
                }
                for code, snapshot in self._memory.items()
            }
            stats = dict(self._stats)
        return {
            "size": len(translations),
            "limit": self.memory_limit,
            "active_locks": self._locks.size,
            "translations": translations,
            "require_checksums": self.require_checksums,
            "validation_version": self.VALIDATION_VERSION,
            **stats,
        }

    def _refresh(
        self,
        abbreviation: str,
        paths: dict[str, Path],
        disk: TranslationSnapshot | None,
        now: float,
    ) -> TranslationSnapshot:
        try:
            remote_sha = self.repository.fetch_text(f"{abbreviation}.sha").strip().lower()
        except RepositoryResourceNotFound:
            remote_sha = ""
        if self.require_checksums and not remote_sha:
            raise RepositoryResponseError(
                f"Translation {abbreviation} does not publish a required checksum."
            )
        if remote_sha and not self._valid_sha(remote_sha):
            raise RepositoryResponseError(
                f"Invalid checksum published for translation {abbreviation}."
            )

        books_raw = self.repository.fetch_bytes(f"{abbreviation}/books.json")
        books_index = self._decode_books_index(books_raw, abbreviation)
        books_sha = hashlib.sha1(books_raw, usedforsecurity=False).hexdigest()

        if disk is not None and remote_sha and disk.sha == remote_sha:
            self._validate_books_match(disk.data, books_index, abbreviation)
            snapshot = TranslationSnapshot(disk.data, disk.sha, now)
            self._write_metadata(
                paths["metadata"],
                snapshot,
                payload=f"{disk.sha}.json",
                books_sha=books_sha,
            )
            return snapshot

        raw = self.repository.fetch_bytes(f"{abbreviation}.json")
        self._increment("downloads")
        actual_sha = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
        if remote_sha and actual_sha != remote_sha:
            raise CacheIntegrityError(
                f"Checksum mismatch for translation {abbreviation}: "
                f"expected {remote_sha}, received {actual_sha}."
            )

        data = self._decode_translation(raw, abbreviation, books_index)
        snapshot = TranslationSnapshot(data, actual_sha, now)
        paths["objects"].mkdir(parents=True, exist_ok=True)
        payload = paths["objects"] / f"{actual_sha}.json"
        self._write_content_addressed(payload, raw, actual_sha)
        self._write_metadata(
            paths["metadata"],
            snapshot,
            payload=payload.name,
            books_sha=books_sha,
        )
        return snapshot

    def _read_metadata(self, paths: dict[str, Path]) -> _CacheMetadata | None:
        try:
            metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
            expected_sha = metadata["sha"]
            checked_at = float(metadata["checked_at"])
            payload = metadata["payload"]
            books_sha = metadata["books_sha"]
            source_generation = metadata["source_generation"]
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            metadata.get("validation_version") != self.VALIDATION_VERSION
            or metadata.get("source") != self.repository.repo_path
            or metadata.get("version") != self.repository.version
            or not self._valid_sha(expected_sha)
            or not self._valid_sha(books_sha)
            or not math.isfinite(checked_at)
            or checked_at < 0
            or payload != f"{expected_sha}.json"
            or not isinstance(source_generation, int)
            or isinstance(source_generation, bool)
            or source_generation < 0
        ):
            return None
        return _CacheMetadata(
            expected_sha,
            checked_at,
            payload,
            books_sha,
            source_generation,
        )

    def _read_disk(
        self,
        paths: dict[str, Path],
        metadata: _CacheMetadata | None = None,
    ) -> TranslationSnapshot | None:
        metadata = metadata or self._read_metadata(paths)
        if metadata is None:
            return None
        expected_sha = metadata.sha
        with self._guard:
            source_generation = self._source_generation
        checked_at = (
            metadata.checked_at
            if metadata.source_generation == source_generation
            else 0.0
        )
        payload = paths["objects"] / metadata.payload
        try:
            raw = payload.read_bytes()
        except OSError:
            return None

        actual_sha = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
        if actual_sha != expected_sha:
            LOGGER.warning("Ignoring a corrupt Librarian translation cache entry.")
            return None
        try:
            abbreviation = paths["metadata"].name.removesuffix(".metadata.json")
            data = self._decode_translation(raw, abbreviation)
        except (CacheIntegrityError, RepositoryResponseError):
            LOGGER.warning("Ignoring an invalid Librarian translation cache entry.")
            return None
        return TranslationSnapshot(data, actual_sha, checked_at)

    @classmethod
    def _decode_translation(
        cls,
        raw: bytes,
        abbreviation: str,
        books_index: dict[int, _BookIndexEntry] | None = None,
    ) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RepositoryResponseError(
                f"Translation {abbreviation} is not valid JSON."
            ) from error
        if not isinstance(data, dict) or not isinstance(data.get("books"), list):
            raise CacheIntegrityError(
                f"Translation {abbreviation} does not contain a valid books array."
            )
        if data.get("abbreviation") != abbreviation:
            raise CacheIntegrityError(
                f"Translation payload {data.get('abbreviation')!r} does not match "
                f"requested abbreviation {abbreviation!r}."
            )
        cls._validate_metadata(data, abbreviation)
        books = data["books"]
        if not books or len(books) > cls.MAX_BOOKS:
            raise CacheIntegrityError(
                f"Translation {abbreviation} must contain 1 to {cls.MAX_BOOKS} books."
            )

        seen_books: set[int] = set()
        total_verses = 0
        corpus_books: dict[int, _BookIndexEntry] = {}
        for book in books:
            if not isinstance(book, dict):
                raise CacheIntegrityError("Translation contains a non-object book entry.")
            book_nr = cls._required_integer(
                book, "nr", 1, cls.MAX_BOOK_NUMBER, "book number"
            )
            book_name = cls._required_string(book, "name", cls.MAX_NAME_LENGTH, "book name")
            cls._validate_supplemental_fields(
                book,
                {"nr", "name", "chapters"},
                "book",
            )
            if book_nr in seen_books:
                raise CacheIntegrityError(f"Translation contains duplicate book {book_nr}.")
            seen_books.add(book_nr)
            corpus_books[book_nr] = cls._book_index_entry(book_name, data)
            chapters = book.get("chapters")
            if not isinstance(chapters, list) or not chapters:
                raise CacheIntegrityError(f"Book {book_nr} does not contain chapters.")
            if len(chapters) > cls.MAX_CHAPTERS_PER_BOOK:
                raise CacheIntegrityError(f"Book {book_nr} exceeds the chapter ceiling.")
            seen_chapters: set[int] = set()
            for chapter in chapters:
                if not isinstance(chapter, dict):
                    raise CacheIntegrityError(f"Book {book_nr} contains an invalid chapter.")
                chapter_nr = cls._required_integer(
                    chapter, "chapter", 1, cls.MAX_CHAPTER_NUMBER, "chapter number"
                )
                cls._required_string(
                    chapter, "name", cls.MAX_NAME_LENGTH, "chapter name"
                )
                cls._validate_supplemental_fields(
                    chapter,
                    {"chapter", "name", "verses"},
                    "chapter",
                )
                if chapter_nr in seen_chapters:
                    raise CacheIntegrityError(
                        f"Book {book_nr} contains duplicate chapter {chapter_nr}."
                    )
                seen_chapters.add(chapter_nr)
                verses = chapter.get("verses")
                if not isinstance(verses, list) or not verses:
                    raise CacheIntegrityError(
                        f"Book {book_nr} chapter {chapter_nr} does not contain verses."
                    )
                if len(verses) > cls.MAX_VERSES_PER_CHAPTER:
                    raise CacheIntegrityError(
                        f"Book {book_nr} chapter {chapter_nr} exceeds the verse ceiling."
                    )
                seen_verses: set[int] = set()
                for verse in verses:
                    if not isinstance(verse, dict):
                        raise CacheIntegrityError(
                            f"Book {book_nr} chapter {chapter_nr} contains an invalid verse."
                        )
                    verse_chapter = cls._required_integer(
                        verse, "chapter", 1, cls.MAX_CHAPTER_NUMBER, "verse chapter"
                    )
                    verse_nr = cls._required_integer(
                        verse, "verse", 1, cls.MAX_VERSE_NUMBER, "verse number"
                    )
                    cls._required_string(verse, "name", cls.MAX_NAME_LENGTH, "verse name")
                    cls._required_string(
                        verse,
                        "text",
                        cls.MAX_TEXT_LENGTH,
                        "verse text",
                        allow_empty=True,
                    )
                    cls._validate_supplemental_fields(
                        verse,
                        {"chapter", "verse", "name", "text"},
                        "verse",
                    )
                    if verse_chapter != chapter_nr:
                        raise CacheIntegrityError(
                            f"Verse {book_nr}:{chapter_nr}:{verse_nr} has a mismatched chapter."
                        )
                    if verse_nr in seen_verses:
                        raise CacheIntegrityError(
                            f"Book {book_nr} chapter {chapter_nr} contains duplicate verse "
                            f"{verse_nr}."
                        )
                    seen_verses.add(verse_nr)
                    total_verses += 1
                    if total_verses > cls.MAX_TOTAL_VERSES:
                        raise CacheIntegrityError("Translation exceeds the total verse ceiling.")

        if books_index is not None and corpus_books != books_index:
            raise CacheIntegrityError(
                f"Translation {abbreviation} does not match its independent books index."
            )
        return data

    @classmethod
    def _decode_books_index(
        cls,
        raw: bytes,
        abbreviation: str,
    ) -> dict[int, _BookIndexEntry]:
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RepositoryResponseError(
                f"Books index for {abbreviation} is not valid JSON."
            ) from error
        if not isinstance(data, dict) or not data or len(data) > cls.MAX_BOOKS:
            raise CacheIntegrityError(
                f"Books index for {abbreviation} does not contain a bounded object."
            )
        result: dict[int, _BookIndexEntry] = {}
        for key, book in data.items():
            if not isinstance(key, str) or not key.isascii() or not key.isdigit():
                raise CacheIntegrityError("Books index contains an invalid book key.")
            if not isinstance(book, dict):
                raise CacheIntegrityError("Books index contains a non-object book.")
            nr = cls._required_integer(book, "nr", 1, cls.MAX_BOOK_NUMBER, "book number")
            name = cls._required_string(book, "name", cls.MAX_NAME_LENGTH, "book name")
            if int(key) != nr or nr in result:
                raise CacheIntegrityError("Books index contains inconsistent book numbers.")
            if book.get("abbreviation") != abbreviation:
                raise CacheIntegrityError(
                    f"Books index payload does not match abbreviation {abbreviation}."
                )
            cls._validate_supplemental_fields(
                book,
                {"nr", "name", *cls.BOOK_INDEX_METADATA},
                "books index entry",
            )
            result[nr] = cls._book_index_entry(name, book)
        return result

    @classmethod
    def validate_chapter_payload(
        cls,
        data: object,
        abbreviation: str,
        book_nr: int,
        chapter_nr: int,
    ) -> None:
        """Validate a lightweight chapter response before retaining it."""
        if not isinstance(data, dict):
            raise CacheIntegrityError(
                f"Invalid chapter structure for {abbreviation} {book_nr}:{chapter_nr}."
            )
        if data.get("abbreviation") != abbreviation:
            raise CacheIntegrityError("Chapter payload contains a mismatched abbreviation.")
        if cls._required_integer(
            data, "book_nr", 1, cls.MAX_BOOK_NUMBER, "book number"
        ) != book_nr:
            raise CacheIntegrityError("Chapter payload contains a mismatched book number.")
        if cls._required_integer(
            data, "chapter", 1, cls.MAX_CHAPTER_NUMBER, "chapter number"
        ) != chapter_nr:
            raise CacheIntegrityError("Chapter payload contains a mismatched chapter number.")
        cls._required_string(data, "book_name", cls.MAX_NAME_LENGTH, "book name")
        cls._required_string(data, "name", cls.MAX_NAME_LENGTH, "chapter name")
        cls._validate_supplemental_fields(
            data,
            {
                "book_nr",
                "book_name",
                "chapter",
                "name",
                "verses",
                *cls.BOOK_INDEX_METADATA,
            },
            "chapter payload",
        )
        verses = data.get("verses")
        if (
            not isinstance(verses, list)
            or not verses
            or len(verses) > cls.MAX_VERSES_PER_CHAPTER
        ):
            raise CacheIntegrityError("Chapter payload contains an invalid verse array.")
        seen: set[int] = set()
        for verse in verses:
            if not isinstance(verse, dict):
                raise CacheIntegrityError("Chapter payload contains an invalid verse.")
            if cls._required_integer(
                verse, "chapter", 1, cls.MAX_CHAPTER_NUMBER, "verse chapter"
            ) != chapter_nr:
                raise CacheIntegrityError("Chapter verse contains a mismatched chapter number.")
            verse_nr = cls._required_integer(
                verse, "verse", 1, cls.MAX_VERSE_NUMBER, "verse number"
            )
            cls._required_string(verse, "name", cls.MAX_NAME_LENGTH, "verse name")
            cls._required_string(
                verse,
                "text",
                cls.MAX_TEXT_LENGTH,
                "verse text",
                allow_empty=True,
            )
            cls._validate_supplemental_fields(
                verse,
                {"chapter", "verse", "name", "text"},
                "chapter verse",
            )
            if verse_nr in seen:
                raise CacheIntegrityError("Chapter payload contains a duplicate verse number.")
            seen.add(verse_nr)

    @classmethod
    def _validate_books_match(
        cls,
        data: dict[str, Any],
        books_index: dict[int, _BookIndexEntry],
        abbreviation: str,
    ) -> None:
        try:
            corpus_books = {
                int(book["nr"]): cls._book_index_entry(str(book["name"]), data)
                for book in data["books"]
            }
        except (KeyError, TypeError, ValueError) as error:
            raise CacheIntegrityError(
                f"Translation {abbreviation} contains invalid cached book data."
            ) from error
        if corpus_books != books_index:
            raise CacheIntegrityError(
                f"Translation {abbreviation} does not match its independent books index."
            )

    @classmethod
    def _book_index_entry(
        cls,
        name: str,
        source: dict[str, Any],
    ) -> _BookIndexEntry:
        metadata: list[tuple[str, str]] = []
        for field in cls.BOOK_INDEX_METADATA:
            value = source.get(field)
            if not isinstance(value, str) or not value or len(value) > cls.MAX_NAME_LENGTH:
                raise CacheIntegrityError(
                    f"Books index contains an invalid {field!r} field."
                )
            metadata.append((field, value))
        return _BookIndexEntry(name, tuple(metadata))

    @classmethod
    def _validate_metadata(cls, data: dict[str, Any], abbreviation: str) -> None:
        if len(data) > cls.MAX_METADATA_ITEMS:
            raise CacheIntegrityError(
                f"Translation {abbreviation} contains too many metadata fields."
            )
        for key, value in data.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise CacheIntegrityError(
                    f"Translation {abbreviation} contains an invalid metadata key."
                )
            if key == "books":
                continue
            cls._validate_metadata_value(value, 0, f"metadata field {key!r}")
        cls._required_string(
            data, "translation", cls.MAX_NAME_LENGTH, "translation name"
        )
        cls._required_string(
            data, "abbreviation", 30, "translation abbreviation"
        )

    @classmethod
    def _validate_supplemental_fields(
        cls,
        value: dict[str, Any],
        structural_fields: set[str],
        label: str,
    ) -> None:
        if len(value) > cls.MAX_METADATA_ITEMS:
            raise CacheIntegrityError(f"Translation {label} contains too many fields.")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise CacheIntegrityError(f"Translation {label} contains an invalid field name.")
            if key not in structural_fields:
                cls._validate_metadata_value(item, 0, f"{label} field {key!r}")

    @classmethod
    def _validate_metadata_value(cls, value: Any, depth: int, label: str) -> None:
        if depth > cls.MAX_METADATA_DEPTH:
            raise CacheIntegrityError(f"Translation {label} exceeds the nesting ceiling.")
        if isinstance(value, str):
            if len(value) > cls.MAX_TEXT_LENGTH:
                raise CacheIntegrityError(f"Translation {label} exceeds the text ceiling.")
            return
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, int):
            if abs(value) > cls.MAX_METADATA_INTEGER:
                raise CacheIntegrityError(f"Translation {label} exceeds the numeric ceiling.")
            return
        if isinstance(value, float):
            if not math.isfinite(value) or abs(value) > cls.MAX_METADATA_INTEGER:
                raise CacheIntegrityError(f"Translation {label} exceeds the numeric ceiling.")
            return
        if isinstance(value, dict):
            if len(value) > cls.MAX_METADATA_ITEMS:
                raise CacheIntegrityError(f"Translation {label} contains too many entries.")
            for key, item in value.items():
                if not isinstance(key, str) or not key or len(key) > 128:
                    raise CacheIntegrityError(f"Translation {label} has an invalid key.")
                cls._validate_metadata_value(item, depth + 1, label)
            return
        if isinstance(value, list):
            if len(value) > cls.MAX_METADATA_ITEMS:
                raise CacheIntegrityError(f"Translation {label} contains too many entries.")
            for item in value:
                cls._validate_metadata_value(item, depth + 1, label)
            return
        raise CacheIntegrityError(f"Translation {label} contains an unsupported value.")

    @staticmethod
    def _required_integer(
        value: dict[str, Any],
        key: str,
        minimum: int,
        maximum: int,
        label: str,
    ) -> int:
        result = value.get(key)
        if not isinstance(result, int) or isinstance(result, bool):
            raise CacheIntegrityError(f"Translation contains an invalid {label}.")
        if not minimum <= result <= maximum:
            raise CacheIntegrityError(
                f"Translation {label} must be between {minimum} and {maximum}."
            )
        return result

    @staticmethod
    def _required_string(
        value: dict[str, Any],
        key: str,
        maximum: int,
        label: str,
        *,
        allow_empty: bool = False,
    ) -> str:
        result = value.get(key)
        if not isinstance(result, str):
            raise CacheIntegrityError(f"Translation contains an invalid {label}.")
        if (not allow_empty and not result.strip()) or len(result) > maximum:
            raise CacheIntegrityError(f"Translation contains an invalid {label}.")
        return result

    def _paths(self, abbreviation: str) -> dict[str, Path]:
        namespace = hashlib.sha256(
            f"{self.repository.repo_path}|{self.repository.version}".encode()
        ).hexdigest()[:16]
        directory = self.cache_dir / namespace / self.repository.version
        return {
            "directory": directory,
            "objects": directory / "objects",
            "metadata": directory / f"{abbreviation}.metadata.json",
            "lock": directory / f"{abbreviation}.lock",
        }

    @staticmethod
    def _cache_root(cache_dir: str | os.PathLike[str] | None) -> Path:
        if cache_dir is not None:
            return Path(cache_dir).expanduser()
        configured = os.environ.get("GETBIBLE_CACHE_DIR")
        if configured:
            return Path(configured).expanduser()
        xdg_cache = os.environ.get("XDG_CACHE_HOME")
        base = Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
        return base / "getbible"

    def _write_metadata(
        self,
        path: Path,
        snapshot: TranslationSnapshot,
        *,
        payload: str | None = None,
        books_sha: str | None = None,
    ) -> None:
        existing = self._read_metadata({"metadata": path})
        payload = payload or (existing.payload if existing is not None else f"{snapshot.sha}.json")
        books_sha = books_sha or (existing.books_sha if existing is not None else "")
        if not self._valid_sha(books_sha):
            raise CacheIntegrityError(
                "Cannot commit translation metadata without a books checksum."
            )
        metadata = json.dumps(
            {
                "validation_version": self.VALIDATION_VERSION,
                "sha": snapshot.sha,
                "checked_at": snapshot.checked_at,
                "payload": payload,
                "books_sha": books_sha,
                "source_generation": self._source_generation,
                "source": self.repository.repo_path,
                "version": self.repository.version,
            },
            sort_keys=True,
        ).encode("utf-8")
        self._write_atomic(path, metadata)

    @staticmethod
    def _write_content_addressed(path: Path, content: bytes, expected_sha: str) -> None:
        if path.exists():
            try:
                existing_sha = hashlib.sha1(
                    path.read_bytes(), usedforsecurity=False
                ).hexdigest()
            except OSError:
                existing_sha = ""
            if existing_sha == expected_sha:
                return
        TranslationCache._write_atomic(path, content)

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)

    def _remember(
        self, abbreviation: str, snapshot: TranslationSnapshot
    ) -> TranslationSnapshot:
        with self._guard:
            if self.memory_limit == 0:
                self._memory.pop(abbreviation, None)
                return snapshot
            self._memory[abbreviation] = snapshot
            self._memory.move_to_end(abbreviation)
            while (
                self.memory_limit is not None
                and len(self._memory) > self.memory_limit
            ):
                self._memory.popitem(last=False)
                self._stats["evictions"] += 1
        return snapshot

    def _is_fresh(
        self,
        abbreviation: str,
        snapshot: TranslationSnapshot,
        now: float,
    ) -> bool:
        if self.refresh_seconds <= 0:
            return False
        key = f"{os.getpid()}:{abbreviation}:{snapshot.sha}".encode()
        jitter_value = int.from_bytes(
            hashlib.blake2b(key, digest_size=8).digest(),
            "big",
        ) / ((1 << 64) - 1)
        refresh_window = self.refresh_seconds * (
            1 - (self.refresh_jitter * jitter_value)
        )
        return now - snapshot.checked_at < refresh_window

    def _increment(self, name: str) -> None:
        with self._guard:
            self._stats[name] += 1

    @staticmethod
    def _validated_limit(name: str, value: int | None) -> int | None:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an integer or null.")
        if value < 0:
            raise ValueError(f"{name} cannot be negative.")
        return value

    @staticmethod
    def _valid_sha(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 40
            and all(character in "0123456789abcdef" for character in value.lower())
        )
