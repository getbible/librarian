"""Small reference-counted keyed lock pool used by in-process caches."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass(slots=True)
class _LockEntry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    users: int = 0


class KeyedLockPool:
    """Serialize work per key without retaining inactive lock objects forever."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._entries: dict[str, _LockEntry] = {}

    @contextmanager
    def hold(self, key: str) -> Iterator[None]:
        with self._guard:
            entry = self._entries.setdefault(key, _LockEntry())
            entry.users += 1
        try:
            with entry.lock:
                yield
        finally:
            with self._guard:
                entry.users -= 1
                if entry.users == 0 and self._entries.get(key) is entry:
                    self._entries.pop(key, None)

    @property
    def size(self) -> int:
        """Return the number of keys currently held or awaited."""
        with self._guard:
            return len(self._entries)
