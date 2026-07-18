"""Persistent, checksum-validated full-translation caching."""

from __future__ import annotations

import hashlib
import json
import logging
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


class TranslationCache:
    """Coordinate in-memory and cross-process on-disk translation caching."""

    def __init__(
        self,
        repository: RepositoryClient,
        refresh_seconds: float,
        cache_dir: str | os.PathLike[str] | None = None,
        strict_freshness: bool = False,
        lock_timeout: float = 120.0,
        memory_limit: int | None = 4,
        refresh_jitter: float = 0.1,
    ) -> None:
        self.repository = repository
        self.refresh_seconds = max(0.0, refresh_seconds)
        self.cache_dir = self._cache_root(cache_dir)
        self.strict_freshness = strict_freshness
        self.lock_timeout = lock_timeout
        self.memory_limit = self._validated_limit("memory_limit", memory_limit)
        if not isinstance(refresh_jitter, (int, float)) or isinstance(
            refresh_jitter, bool
        ):
            raise TypeError("refresh_jitter must be a number.")
        if not 0 <= refresh_jitter < 1:
            raise ValueError("refresh_jitter must be between 0 (inclusive) and 1.")
        self.refresh_jitter = float(refresh_jitter)
        self._memory: OrderedDict[str, TranslationSnapshot] = OrderedDict()
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
                    and metadata[0] == memory.sha
                ):
                    disk = TranslationSnapshot(
                        memory.data,
                        memory.sha,
                        metadata[1],
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
                except RepositoryError:
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
        if remote_sha and not self._valid_sha(remote_sha):
            raise RepositoryResponseError(
                f"Invalid checksum published for translation {abbreviation}."
            )

        if disk is not None and remote_sha and disk.sha == remote_sha:
            snapshot = TranslationSnapshot(disk.data, disk.sha, now)
            self._write_metadata(paths["metadata"], snapshot)
            return snapshot

        raw = self.repository.fetch_bytes(f"{abbreviation}.json")
        self._increment("downloads")
        actual_sha = hashlib.sha1(raw).hexdigest()
        if remote_sha and actual_sha != remote_sha:
            raise CacheIntegrityError(
                f"Checksum mismatch for translation {abbreviation}: "
                f"expected {remote_sha}, received {actual_sha}."
            )

        data = self._decode_translation(raw, abbreviation)
        snapshot = TranslationSnapshot(data, actual_sha, now)
        self._write_atomic(paths["translation"], raw)
        self._write_metadata(paths["metadata"], snapshot)
        return snapshot

    def _read_metadata(self, paths: dict[str, Path]) -> tuple[str, float] | None:
        try:
            metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
            expected_sha = metadata["sha"]
            checked_at = float(metadata["checked_at"])
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if not self._valid_sha(expected_sha):
            return None
        return expected_sha, checked_at

    def _read_disk(
        self,
        paths: dict[str, Path],
        metadata: tuple[str, float] | None = None,
    ) -> TranslationSnapshot | None:
        metadata = metadata or self._read_metadata(paths)
        if metadata is None:
            return None
        expected_sha, checked_at = metadata
        try:
            raw = paths["translation"].read_bytes()
        except OSError:
            return None

        actual_sha = hashlib.sha1(raw).hexdigest()
        if actual_sha != expected_sha:
            LOGGER.warning("Ignoring a corrupt Librarian translation cache entry.")
            return None
        try:
            data = self._decode_translation(raw, paths["translation"].stem)
        except (CacheIntegrityError, RepositoryResponseError):
            LOGGER.warning("Ignoring an invalid Librarian translation cache entry.")
            return None
        return TranslationSnapshot(data, actual_sha, checked_at)

    @staticmethod
    def _decode_translation(raw: bytes, abbreviation: str) -> dict[str, Any]:
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
        return data

    def _paths(self, abbreviation: str) -> dict[str, Path]:
        namespace = hashlib.sha256(
            f"{self.repository.repo_path}|{self.repository.version}".encode()
        ).hexdigest()[:16]
        directory = self.cache_dir / namespace / self.repository.version
        return {
            "directory": directory,
            "translation": directory / f"{abbreviation}.json",
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

    def _write_metadata(self, path: Path, snapshot: TranslationSnapshot) -> None:
        metadata = json.dumps(
            {
                "sha": snapshot.sha,
                "checked_at": snapshot.checked_at,
                "source": self.repository.repo_path,
                "version": self.repository.version,
            },
            sort_keys=True,
        ).encode("utf-8")
        self._write_atomic(path, metadata)

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
