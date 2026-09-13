"""Explicit metadata contracts for public scripture and search results."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

_TRANSLATION_FIELDS = (
    "translation", "abbreviation", "lang", "language", "direction", "encoding",
)
_CHAPTER_FIELDS = _TRANSLATION_FIELDS + ("book_nr", "book_name", "chapter", "name")


def translation_metadata(data: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only the six API translation labels that the source provides.

    Full translation descriptions, history and other source metadata belong to
    the static API. Preserve original values, including empty optional labels,
    without inventing values for fields absent from a compatible repository.
    """
    return {key: deepcopy(data[key]) for key in _TRANSLATION_FIELDS if key in data}


def chapter_metadata(data: Mapping[str, Any]) -> dict[str, Any]:
    """Copy translation labels and chapter identity, excluding source extras."""
    return {key: deepcopy(data[key]) for key in _CHAPTER_FIELDS if key in data}
