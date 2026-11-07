"""Detach validated JSON values from immutable source and cache objects."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def copy_json(value: Any) -> Any:
    """Copy JSON containers iteratively, preserving order and shared branches.

    Source validation already checks the values. This copy keeps callers from
    mutating retained data without ``deepcopy``'s lower recursion threshold.
    Iterators retain only the active ancestor path; the memo maps containers
    to their copies, as ``deepcopy`` does. Cycles are not valid JSON.
    """
    if not isinstance(value, (dict, list)):
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        raise TypeError("Only JSON values can be copied.")

    copied: dict | list = {} if isinstance(value, dict) else []
    memo: dict[int, dict | list] = {id(value): copied}
    ancestors = {id(value)}
    entries = iter(value.items()) if isinstance(value, dict) else enumerate(value)
    stack: list[tuple[Iterator, dict | list, int]] = [(entries, copied, id(value))]
    while stack:
        entries, target, identity = stack[-1]
        try:
            key, item = next(entries)
        except StopIteration:
            stack.pop()
            ancestors.remove(identity)
            continue

        if isinstance(item, (dict, list)):
            item_id = id(item)
            if item_id in ancestors:
                raise ValueError("Circular reference detected")
            child = memo.get(item_id)
            if child is None:
                child = {} if isinstance(item, dict) else []
                memo[item_id] = child
                children = iter(item.items()) if isinstance(item, dict) else enumerate(item)
                ancestors.add(item_id)
                stack.append((children, child, item_id))
        elif item is None or isinstance(item, (str, bool, int, float)):
            child = item
        else:
            raise TypeError("Only JSON values can be copied.")
        if isinstance(target, dict):
            target[key] = child
        else:
            target.append(child)
    return copied
