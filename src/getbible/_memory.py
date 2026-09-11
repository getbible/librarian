"""Conservative Python object size estimates, never process RSS measurements."""

from __future__ import annotations

import sys
from collections import deque
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any


def estimated_bytes(value: Any, seen: set[int] | None = None) -> int:
    """Count reachable owned containers/records, deduplicating shared objects.

    Native allocator overhead, fragmentation, locks and process memory are not
    represented. Arrays include their native buffer in ``sys.getsizeof``.
    This is for cache admission and operator estimates, not an RSS guarantee.
    """
    visited = set() if seen is None else seen
    pending = [value]
    total = 0
    while pending:
        item = pending.pop()
        identity = id(item)
        if identity in visited:
            continue
        visited.add(identity)
        total += sys.getsizeof(item)
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple, set, frozenset, deque)):
            pending.extend(item)
        elif isinstance(item, Enum):
            continue
        elif is_dataclass(item) and not isinstance(item, type):
            pending.extend(getattr(item, field.name) for field in fields(item))
        elif type(item).__module__.startswith("getbible."):
            if hasattr(item, "__dict__"):
                pending.append(vars(item))
            for slot in getattr(type(item), "__slots__", ()):
                if slot not in {"__weakref__", "__dict__"} and hasattr(item, slot):
                    pending.append(getattr(item, slot))
    return total


UNSET = object()
