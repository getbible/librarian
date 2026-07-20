"""Atomic source generations for multi-worker cache coordination."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from filelock import FileLock

from .exceptions import CacheIntegrityError

try:  # pragma: no cover - exercised by Linux CI and production deployments.
    import fcntl
except ImportError:  # pragma: no cover - Windows uses the process-local barrier.
    fcntl = None


@dataclass(frozen=True, slots=True)
class SourceGeneration:
    """One committed repository generation and its stable cache namespace."""

    namespace: str
    generation: int
    revision: str
    updated_at: float

    @property
    def cache_namespace(self) -> str:
        """Return a response-cache prefix that changes only after a transition."""
        return f"{self.namespace}:g{self.generation}"

    def to_dict(self) -> dict[str, str | int | float]:
        return {**asdict(self), "cache_namespace": self.cache_namespace}


PurgeCallback = Callable[[SourceGeneration, SourceGeneration], None]
InvalidateCallback = Callable[[SourceGeneration], None]


class _ReaderWriterBarrier:
    """Writer-preferring reader/writer barrier for threads in one process."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @contextmanager
    def read(self) -> Iterator[None]:
        with self._condition:
            while self._writer or self._waiting_writers:
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @contextmanager
    def write(self) -> Iterator[None]:
        with self._condition:
            self._waiting_writers += 1
            try:
                while self._writer or self._readers:
                    self._condition.wait()
                self._writer = True
            finally:
                self._waiting_writers -= 1
        try:
            yield
        finally:
            with self._condition:
                self._writer = False
                self._condition.notify_all()


class SourceCoordinator:
    """Coordinate source transitions and cache invalidation across workers.

    Readers hold a shared operating-system lock for the complete operation.
    Transitions hold the exclusive form of that lock, serialize the purge
    callback, and atomically commit the new manifest only after purge succeeds.
    """

    MANIFEST_VERSION = 1
    MAX_REVISION_LENGTH = 256

    def __init__(
        self,
        cache_root: Path,
        source: str,
        version: str,
        invalidate_callback: InvalidateCallback,
        purge_callback: PurgeCallback | None = None,
    ) -> None:
        self.namespace = hashlib.sha256(f"{source}|{version}".encode()).hexdigest()[:16]
        self.directory = cache_root / self.namespace / version
        self.manifest_path = self.directory / "source-generation.json"
        self.transition_lock_path = self.directory / "source-transition.lock"
        self.barrier_path = self.directory / "source-transition.barrier"
        self.invalidate_callback = invalidate_callback
        self.purge_callback = purge_callback
        self._barrier = _ReaderWriterBarrier()
        self._state_guard = threading.Lock()
        self._thread_local = threading.local()
        self._observed = self._read_manifest()

    @contextmanager
    def source_operation(self) -> Iterator[SourceGeneration]:
        """Hold a stable generation across source reads and cache transactions."""
        depth = getattr(self._thread_local, "operation_depth", 0)
        if depth:
            self._thread_local.operation_depth = depth + 1
            try:
                yield self._thread_local.operation_state
            finally:
                self._thread_local.operation_depth -= 1
            return

        self.synchronize()
        with self._barrier.read(), self._file_barrier(shared=True):
            state = self._read_manifest()
            self._thread_local.operation_depth = 1
            self._thread_local.operation_state = state
            try:
                yield state
            finally:
                del self._thread_local.operation_state
                del self._thread_local.operation_depth

    def synchronize(self) -> SourceGeneration:
        """Invalidate this worker when another worker committed a generation."""
        current = self._read_manifest()
        with self._state_guard:
            observed = self._observed
        if current.generation == observed.generation:
            return current

        with self._barrier.write(), self._file_barrier(shared=True):
            current = self._read_manifest()
            with self._state_guard:
                observed = self._observed
            if current.generation != observed.generation:
                self.invalidate_callback(current)
                with self._state_guard:
                    self._observed = current
        return current

    def transition(
        self,
        revision: str,
        purge_callback: PurgeCallback | None = None,
    ) -> SourceGeneration:
        """Atomically activate an immutable mirror revision.

        The purge callback executes while every source reader is excluded. If it
        raises, the manifest remains unchanged and a later caller can retry the
        same transition without exposing a partially invalidated generation.
        """
        revision = self._validated_revision(revision)
        if getattr(self._thread_local, "operation_depth", 0):
            raise RuntimeError("Cannot transition the source inside source_operation().")
        self.directory.mkdir(parents=True, exist_ok=True)

        with (
            self._barrier.write(),
            FileLock(str(self.transition_lock_path)),
            self._file_barrier(shared=False),
        ):
            current = self._read_manifest()
            if current.revision == revision:
                with self._state_guard:
                    self._observed = current
                return current

            candidate = SourceGeneration(
                namespace=self.namespace,
                generation=current.generation + 1,
                revision=revision,
                updated_at=time.time(),
            )
            callback = purge_callback or self.purge_callback
            if callback is not None:
                callback(current, candidate)
            self._write_manifest(candidate)
            self.invalidate_callback(candidate)
            with self._state_guard:
                self._observed = candidate
            return candidate

    def info(self) -> dict[str, str | int | float]:
        return self.synchronize().to_dict()

    def _read_manifest(self) -> SourceGeneration:
        try:
            raw = self.manifest_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return SourceGeneration(self.namespace, 0, "initial", 0.0)
        except OSError as error:
            raise CacheIntegrityError("Unable to read the source generation manifest.") from error
        try:
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("manifest is not an object")
            if value.get("manifest_version") != self.MANIFEST_VERSION:
                raise ValueError("unsupported manifest version")
            if value.get("namespace") != self.namespace:
                raise ValueError("manifest namespace mismatch")
            generation = value["generation"]
            revision = value["revision"]
            updated_at = value["updated_at"]
            if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
                raise ValueError("invalid generation")
            revision = self._validated_revision(revision)
            if not isinstance(updated_at, int | float) or isinstance(updated_at, bool):
                raise ValueError("invalid update time")
            return SourceGeneration(
                namespace=self.namespace,
                generation=generation,
                revision=revision,
                updated_at=float(updated_at),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise CacheIntegrityError("Invalid source generation manifest.") from error

    def _write_manifest(self, state: SourceGeneration) -> None:
        content = json.dumps(
            {"manifest_version": self.MANIFEST_VERSION, **asdict(state)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.manifest_path.name}.",
            suffix=".tmp",
            dir=self.directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.manifest_path)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)

    @contextmanager
    def _file_barrier(self, *, shared: bool) -> Iterator[None]:
        # The first reader must create the common lock location before it can
        # observe a generation. Otherwise a concurrent first transition in a
        # different worker could create and take the barrier while that reader
        # proceeded without a file lock.
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Read-only clients can still validate absent translations and
            # inspect process-local telemetry. Any operation that actually
            # needs the shared disk cache or a transition will fail at its own
            # write boundary; the in-process reader/writer barrier remains held.
            yield
            return
        descriptor = os.open(self.barrier_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if fcntl is not None:
                operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
                fcntl.flock(descriptor, operation)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @classmethod
    def _validated_revision(cls, revision: object) -> str:
        if not isinstance(revision, str):
            raise TypeError("source revision must be a string.")
        value = revision.strip()
        if not value or len(value) > cls.MAX_REVISION_LENGTH:
            raise ValueError(
                f"source revision must contain 1 to {cls.MAX_REVISION_LENGTH} characters."
            )
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("source revision cannot contain control characters.")
        return value
