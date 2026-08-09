"""Validated, serializable search behaviour.

Every field here is optional. A caller that supplies nothing gets a search that
works correctly in every writing system the API publishes, because the engine
derives its matching strategy from the text rather than from a flag. The
criteria exist to *narrow* a search — a testament, a book, an exclusion — not to
tell the engine how to read a script.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar

from ..exceptions import SearchValidationError

__all__ = ["SearchBible", "SearchCriteria"]

_VALID_WORDS = frozenset({"all", "any", "phrase"})
_VALID_MATCH = frozenset({"whole_word", "substring"})
_VALID_SCOPE = frozenset({"bible", "old_testament", "new_testament", "deuterocanon"})
_VALID_SORT = frozenset({"canonical", "relevance"})

#: 1.x spelled the diacritic policy "sensitive"/"insensitive". The behaviour is
#: clearer as "exact"/"fold", and the default moved to folding so that a reader
#: typing unaccented Greek or unpointed Hebrew reaches the text. Both spellings
#: are accepted so existing callers keep working.
_DIACRITIC_ALIASES = {
    "sensitive": "exact",
    "insensitive": "fold",
    "exact": "exact",
    "fold": "fold",
}
_VALID_DIACRITICS = frozenset({"exact", "fold"})


@dataclass(frozen=True, slots=True)
class SearchBible:
    """Validated Bible search behaviour."""

    MAX_LIMIT: ClassVar[int] = 1000
    words: str = "all"
    match: str = "whole_word"
    case_sensitive: bool = False
    scope: str = "bible"
    books: tuple[int | str, ...] = field(default_factory=tuple)
    diacritics: str = "fold"
    exclude: tuple[str, ...] = field(default_factory=tuple)
    proximity: int | None = None
    sort: str = "canonical"
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        for name in ("words", "match", "scope", "diacritics", "sort"):
            if not isinstance(getattr(self, name), str):
                raise SearchValidationError(f"{name} must be a string.")
        object.__setattr__(self, "words", self.words.casefold())
        object.__setattr__(self, "match", self.match.casefold())
        object.__setattr__(self, "scope", self.scope.casefold())
        object.__setattr__(self, "sort", self.sort.casefold())
        object.__setattr__(
            self,
            "diacritics",
            _DIACRITIC_ALIASES.get(self.diacritics.casefold(), self.diacritics.casefold()),
        )
        books = (self.books,) if isinstance(self.books, (str, int)) else tuple(self.books)
        excluded = (self.exclude,) if isinstance(self.exclude, str) else tuple(self.exclude)
        object.__setattr__(self, "books", books)
        object.__setattr__(self, "exclude", excluded)
        self._validate()

    @property
    def fold_diacritics(self) -> bool:
        return self.diacritics == "fold"

    @classmethod
    def from_value(
        cls,
        value: SearchBible | Mapping[str, Any] | str | None,
    ) -> SearchBible:
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls.from_legacy(value)
        if not isinstance(value, Mapping):
            raise SearchValidationError(
                "Search criteria must be a SearchBible object, mapping, or legacy string."
            )
        allowed = {
            "words", "match", "case_sensitive", "scope", "books", "diacritics",
            "exclude", "proximity", "sort", "limit", "offset",
        }
        unknown = set(value) - allowed
        if unknown:
            raise SearchValidationError(
                f"Unknown search criteria: {', '.join(sorted(unknown))}."
            )
        try:
            return cls(**dict(value))
        except TypeError as error:
            raise SearchValidationError(str(error)) from error

    @classmethod
    def from_legacy(cls, value: str) -> SearchBible:
        parts = value.split("-")
        if len(parts) != 4:
            raise SearchValidationError(f"Invalid legacy search criteria '{value}'.")
        words, match, case, target = parts
        word_map = {"allwords": "all", "anywords": "any", "exactwords": "phrase"}
        match_map = {"exactmatch": "whole_word", "partialmatch": "substring"}
        case_map = {"caseinsensitive": False, "casesensitive": True}
        scope_map = {
            "allbooks": "bible",
            "oldtestament": "old_testament",
            "newtestament": "new_testament",
            "deuterocanon": "deuterocanon",
        }
        if words not in word_map or match not in match_map or case not in case_map:
            raise SearchValidationError(f"Invalid legacy search criteria '{value}'.")
        if target in scope_map:
            return cls(
                words=word_map[words],
                match=match_map[match],
                case_sensitive=case_map[case],
                scope=scope_map[target],
            )
        if target.isdigit() and 1 <= int(target) <= 83:
            return cls(
                words=word_map[words],
                match=match_map[match],
                case_sensitive=case_map[case],
                books=(int(target),),
            )
        raise SearchValidationError(f"Invalid legacy search criteria '{value}'.")

    def with_pagination(self, limit: int, offset: int) -> SearchBible:
        return replace(self, limit=limit, offset=offset)

    @property
    def expensive(self) -> bool:
        """Classify strict-rate-tier searches without loading a translation.

        Diacritic folding is no longer listed: it is the default and costs
        nothing at request time, because folding happens once during index
        construction.
        """
        return (
            self.match == "substring"
            or self.words in {"any", "phrase"}
            or self.proximity is not None
            or self.sort == "relevance"
            or bool(self.exclude)
            or self.offset > 1_000
            or self.limit > 100
        )

    @property
    def index_key(self) -> tuple[bool, bool]:
        """The analysed view this search needs."""
        return (self.case_sensitive, self.fold_diacritics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "words": self.words,
            "match": self.match,
            "case_sensitive": self.case_sensitive,
            "scope": self.scope,
            "books": list(self.books),
            "diacritics": self.diacritics,
            "exclude": list(self.exclude),
            "proximity": self.proximity,
            "sort": self.sort,
            "limit": self.limit,
            "offset": self.offset,
        }

    def _validate(self) -> None:
        if self.words not in _VALID_WORDS:
            raise SearchValidationError(f"Invalid words mode '{self.words}'.")
        if self.match not in _VALID_MATCH:
            raise SearchValidationError(f"Invalid match mode '{self.match}'.")
        if not isinstance(self.case_sensitive, bool):
            raise SearchValidationError("case_sensitive must be a boolean.")
        if self.scope not in _VALID_SCOPE:
            raise SearchValidationError(f"Invalid search scope '{self.scope}'.")
        if self.diacritics not in _VALID_DIACRITICS:
            raise SearchValidationError(f"Invalid diacritics mode '{self.diacritics}'.")
        if self.sort not in _VALID_SORT:
            raise SearchValidationError(f"Invalid sort mode '{self.sort}'.")
        if any(not isinstance(book, (int, str)) or isinstance(book, bool) for book in self.books):
            raise SearchValidationError("books must contain only book names or numbers.")
        if any(not isinstance(term, str) or not term.strip() for term in self.exclude):
            raise SearchValidationError("exclude must contain non-empty strings.")
        if self.proximity is not None:
            if not isinstance(self.proximity, int) or isinstance(self.proximity, bool):
                raise SearchValidationError("proximity must be an integer or null.")
            if self.proximity < 0 or self.proximity > 100:
                raise SearchValidationError("proximity must be between 0 and 100.")
            if self.words != "all":
                raise SearchValidationError("proximity is supported only with words='all'.")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool):
            raise SearchValidationError("limit must be an integer.")
        if not 1 <= self.limit <= self.MAX_LIMIT:
            raise SearchValidationError(f"limit must be between 1 and {self.MAX_LIMIT}.")
        if not isinstance(self.offset, int) or isinstance(self.offset, bool) or self.offset < 0:
            raise SearchValidationError("offset must be a non-negative integer.")


# Compatibility for integrations that adopted the pre-1.2 development name.
SearchCriteria = SearchBible
