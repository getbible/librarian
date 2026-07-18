"""Unicode-aware, JSON-friendly scripture search engine."""

from __future__ import annotations

import threading
import unicodedata
from array import array
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import groupby
from typing import Any, ClassVar

import regex

from .exceptions import CacheIntegrityError, SearchValidationError
from .translation_cache import TranslationSnapshot

_TOKEN_CLASS = r"\p{L}\p{M}\p{N}"
_TOKEN = regex.compile(rf"[{_TOKEN_CLASS}]+(?:['’][{_TOKEN_CLASS}]+)*")
_VALID_WORDS = frozenset({"all", "any", "phrase"})
_VALID_MATCH = frozenset({"whole_word", "substring"})
_VALID_SCOPE = frozenset({"bible", "old_testament", "new_testament", "deuterocanon"})
_VALID_DIACRITICS = frozenset({"sensitive", "insensitive"})
_VALID_SORT = frozenset({"canonical", "relevance"})


@dataclass(frozen=True, slots=True)
class SearchBible:
    """Validated, serializable Bible search behavior."""

    MAX_LIMIT: ClassVar[int] = 1000
    words: str = "all"
    match: str = "whole_word"
    case_sensitive: bool = False
    scope: str = "bible"
    books: tuple[int | str, ...] = field(default_factory=tuple)
    diacritics: str = "sensitive"
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
        object.__setattr__(self, "diacritics", self.diacritics.casefold())
        object.__setattr__(self, "sort", self.sort.casefold())
        books = (self.books,) if isinstance(self.books, (str, int)) else tuple(self.books)
        excluded = (self.exclude,) if isinstance(self.exclude, str) else tuple(self.exclude)
        object.__setattr__(self, "books", books)
        object.__setattr__(self, "exclude", excluded)
        self._validate()

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
            raise SearchValidationError(
                f"limit must be between 1 and {self.MAX_LIMIT}."
            )
        if not isinstance(self.offset, int) or isinstance(self.offset, bool) or self.offset < 0:
            raise SearchValidationError("offset must be a non-negative integer.")


# Compatibility for integrations that adopted the pre-1.2 development name.
SearchCriteria = SearchBible


@dataclass(frozen=True, slots=True)
class VerseRecord:
    ordinal: int
    book_nr: int
    book_name: str
    chapter: int
    chapter_name: str
    verse: dict[str, Any]

    @property
    def text(self) -> str:
        return str(self.verse["text"])

    @property
    def reference(self) -> str:
        return str(self.verse["name"])


@dataclass(frozen=True, slots=True)
class SearchHit:
    record: VerseRecord
    score: int
    occurrences: int
    terms: tuple[str, ...]


@dataclass(slots=True)
class SearchIndex:
    """Compact token postings and normalized verse text for one text mode."""

    texts: tuple[str, ...]
    postings: dict[str, array]
    document_frequency: dict[str, int]


class TranslationCorpus:
    """Immutable canonical verse records with lazily cached text variants."""

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
        self.available_books = frozenset(record.book_nr for record in self.records)
        self.book_names = self._build_book_names(self.records)
        self._variants: dict[tuple[bool, str], SearchIndex] = {}
        self._variant_lock = threading.Lock()

    def index(self, case_sensitive: bool, diacritics: str) -> SearchIndex:
        key = (case_sensitive, diacritics)
        index = self._variants.get(key)
        if index is None:
            with self._variant_lock:
                index = self._variants.get(key)
                if index is None:
                    texts = tuple(
                        normalize_text(record.text, case_sensitive, diacritics)
                        for record in self.records
                    )
                    postings: dict[str, array] = {}
                    document_frequency: dict[str, int] = {}
                    for ordinal, text in enumerate(texts):
                        tokens = _TOKEN.findall(text)
                        for token in tokens:
                            postings.setdefault(token, array("I")).append(ordinal)
                        for token in set(tokens):
                            document_frequency[token] = document_frequency.get(token, 0) + 1
                    index = SearchIndex(
                        texts=texts,
                        postings=postings,
                        document_frequency=document_frequency,
                    )
                    self._variants[key] = index
        return index

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
                normalized = normalize_book_name(book)
                number = self.book_names.get(normalized)
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
            books = sorted(data["books"], key=lambda item: int(item["nr"]))
            for book in books:
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
            raise CacheIntegrityError("Translation contains invalid book or verse data.") from error
        return tuple(records)

    @staticmethod
    def _build_book_names(records: Sequence[VerseRecord]) -> dict[str, int]:
        names: dict[str, int] = {}
        for record in records:
            names[normalize_book_name(record.book_name)] = record.book_nr
        return names


class SearchEngine:
    """Execute criteria against a loaded translation corpus."""

    MAX_QUERY_LENGTH = 500
    MAX_QUERY_TERMS = 64

    def __init__(
        self,
        corpus: TranslationCorpus,
        book_number: Callable[[str], int | None],
    ) -> None:
        self.corpus = corpus
        self.book_number = book_number

    def search(
        self,
        query: str,
        criteria: SearchBible,
    ) -> tuple[list[SearchHit], int]:
        if not isinstance(query, str):
            raise SearchValidationError("Search query must be a string.")
        query = query.strip()
        if not query:
            raise SearchValidationError("Search query cannot be empty.")
        if len(query) > self.MAX_QUERY_LENGTH:
            raise SearchValidationError(
                f"Search query cannot exceed {self.MAX_QUERY_LENGTH} characters."
            )

        normalized_query = normalize_text(
            query, criteria.case_sensitive, criteria.diacritics
        )
        query_terms = tuple(_TOKEN.findall(normalized_query))
        if not query_terms:
            raise SearchValidationError("Search query must contain letters or numbers.")
        if len(query_terms) > self.MAX_QUERY_TERMS:
            raise SearchValidationError(
                f"Search query cannot exceed {self.MAX_QUERY_TERMS} terms."
            )
        if criteria.words != "phrase":
            query_terms = tuple(dict.fromkeys(query_terms))
        excluded = tuple(
            normalize_text(term, criteria.case_sensitive, criteria.diacritics)
            for term in criteria.exclude
        )
        book_filter = self._book_filter(criteria)
        index = self.corpus.index(criteria.case_sensitive, criteria.diacritics)
        if (
            len(query_terms) == 1
            and criteria.match == "whole_word"
            and not excluded
            and criteria.proximity is None
            and criteria.sort == "canonical"
        ):
            return self._single_term_search(
                index, query_terms[0], book_filter, criteria
            )

        matcher = _Matcher(criteria, normalized_query, query_terms, excluded)
        eligible = None
        if book_filter != self.corpus.available_books:
            eligible = frozenset(
                record.ordinal
                for record in self.corpus.records
                if record.book_nr in book_filter
            )
        matched = matcher.search(index, eligible)
        hits = [
            SearchHit(self.corpus.records[ordinal], score, occurrences, terms)
            for ordinal, (score, occurrences, terms) in sorted(matched.items())
        ]

        if criteria.sort == "relevance":
            hits.sort(key=lambda hit: (-hit.score, hit.record.ordinal))
        total = len(hits)
        return hits[criteria.offset:criteria.offset + criteria.limit], total

    def _single_term_search(
        self,
        index: SearchIndex,
        term: str,
        book_filter: frozenset[int],
        criteria: SearchBible,
    ) -> tuple[list[SearchHit], int]:
        selected: list[SearchHit] = []
        whole_corpus = book_filter == self.corpus.available_books
        total = index.document_frequency.get(term, 0) if whole_corpus else 0
        matched_position = 0
        page_end = criteria.offset + criteria.limit
        for ordinal, occurrences_group in groupby(index.postings.get(term, ())):
            occurrences = sum(1 for _ in occurrences_group)
            record = self.corpus.records[ordinal]
            if record.book_nr not in book_filter:
                continue
            if criteria.offset <= matched_position < page_end:
                selected.append(
                    SearchHit(
                        record=record,
                        score=occurrences,
                        occurrences=occurrences,
                        terms=(term,),
                    )
                )
            matched_position += 1
            if whole_corpus and matched_position >= page_end:
                break
        if not whole_corpus:
            total = matched_position
        return selected, total

    def _book_filter(self, criteria: SearchBible) -> frozenset[int]:
        if criteria.scope == "old_testament":
            scoped = {book for book in self.corpus.available_books if 1 <= book <= 39}
        elif criteria.scope == "new_testament":
            scoped = {book for book in self.corpus.available_books if 40 <= book <= 66}
        elif criteria.scope == "deuterocanon":
            scoped = {book for book in self.corpus.available_books if book >= 67}
        else:
            scoped = set(self.corpus.available_books)

        if criteria.books:
            requested = self.corpus.resolve_books(criteria.books, self.book_number)
            scoped.intersection_update(requested)
        return frozenset(scoped)


class _Matcher:
    def __init__(
        self,
        criteria: SearchBible,
        query: str,
        terms: tuple[str, ...],
        excluded: tuple[str, ...],
    ) -> None:
        self.criteria = criteria
        self.query = query
        self.terms = terms
        self.excluded = excluded
        self.excluded_tokens = tuple(
            dict.fromkeys(
                token for value in excluded for token in _TOKEN.findall(value)
            )
        )
        self.phrase_pattern = self._phrase_pattern(terms)

    def search(
        self,
        index: SearchIndex,
        eligible: frozenset[int] | None,
    ) -> dict[int, tuple[int, int, tuple[str, ...]]]:
        if self.criteria.words == "phrase":
            matches = self._phrase_matches(index, eligible)
        else:
            matches = self._word_matches(index, eligible)

        excluded = self._excluded_ordinals(index)
        for ordinal in excluded:
            matches.pop(ordinal, None)

        if self.criteria.proximity is not None:
            matches = {
                ordinal: match
                for ordinal, match in matches.items()
                if self._within_proximity(index.texts[ordinal])
            }
        return matches

    def _phrase_matches(
        self,
        index: SearchIndex,
        eligible: frozenset[int] | None,
    ) -> dict[int, tuple[int, int, tuple[str, ...]]]:
        if self.criteria.match == "substring":
            candidates = eligible if eligible is not None else range(len(index.texts))
        else:
            posting_sets = [set(index.postings.get(term, ())) for term in self.terms]
            if not posting_sets or any(not values for values in posting_sets):
                return {}
            candidates = set.intersection(*posting_sets)
            if eligible is not None:
                candidates.intersection_update(eligible)

        matches: dict[int, tuple[int, int, tuple[str, ...]]] = {}
        for ordinal in candidates:
            text = index.texts[ordinal]
            occurrences = (
                text.count(self.query)
                if self.criteria.match == "substring"
                else len(self.phrase_pattern.findall(text))
            )
            if occurrences:
                score = occurrences * max(1, len(self.terms))
                matches[ordinal] = (score, occurrences, self.terms)
        return matches

    def _word_matches(
        self,
        index: SearchIndex,
        eligible: frozenset[int] | None,
    ) -> dict[int, tuple[int, int, tuple[str, ...]]]:
        per_term = [self._posting_counts(index, term) for term in self.terms]
        ordinal_sets = [set(counts) for counts in per_term]
        if self.criteria.words == "all":
            if any(not values for values in ordinal_sets):
                return {}
            candidates = set.intersection(*ordinal_sets)
        else:
            candidates = set.union(*ordinal_sets) if ordinal_sets else set()
        if eligible is not None:
            candidates.intersection_update(eligible)

        matches: dict[int, tuple[int, int, tuple[str, ...]]] = {}
        for ordinal in candidates:
            counts = tuple(values.get(ordinal, 0) for values in per_term)
            terms = tuple(
                term
                for term, count in zip(self.terms, counts, strict=True)
                if count > 0
            )
            occurrences = sum(counts)
            matches[ordinal] = (occurrences, occurrences, terms)
        return matches

    def _posting_counts(self, index: SearchIndex, term: str) -> Counter[int]:
        if self.criteria.match == "whole_word":
            return Counter(index.postings.get(term, ()))
        counts: Counter[int] = Counter()
        for token, ordinals in index.postings.items():
            if term in token:
                counts.update(ordinals)
        return counts

    def _excluded_ordinals(self, index: SearchIndex) -> set[int]:
        excluded: set[int] = set()
        for term in self.excluded_tokens:
            excluded.update(self._posting_counts(index, term))
        return excluded

    def _within_proximity(self, text: str) -> bool:
        wanted: dict[str, int] = {}
        for term in self.terms:
            wanted[term] = wanted.get(term, 0) + 1
        positions = [match.group() for match in _TOKEN.finditer(text)]
        counts: dict[str, int] = {}
        left = 0
        satisfied = 0
        required = len(wanted)
        for right, token in enumerate(positions):
            if token in wanted:
                counts[token] = counts.get(token, 0) + 1
                if counts[token] == wanted[token]:
                    satisfied += 1
            while satisfied == required and left <= right:
                window_size = right - left + 1
                if window_size - len(self.terms) <= int(self.criteria.proximity):
                    return True
                left_token = positions[left]
                if left_token in wanted:
                    if counts[left_token] == wanted[left_token]:
                        satisfied -= 1
                    counts[left_token] -= 1
                left += 1
        return False

    def _phrase_pattern(self, terms: Sequence[str]) -> regex.Pattern[str]:
        separator = rf"[^{_TOKEN_CLASS}]+"
        body = separator.join(regex.escape(term) for term in terms)
        return regex.compile(
            rf"(?<![{_TOKEN_CLASS}]){body}(?![{_TOKEN_CLASS}])"
        )


def normalize_text(text: str, case_sensitive: bool, diacritics: str) -> str:
    value = unicodedata.normalize("NFC", text)
    value = " ".join(value.split())
    if diacritics == "insensitive":
        value = "".join(
            character
            for character in unicodedata.normalize("NFD", value)
            if unicodedata.category(character) != "Mn"
        )
        value = unicodedata.normalize("NFC", value)
    return value if case_sensitive else value.casefold()


def normalize_book_name(name: str) -> str:
    return "".join(normalize_text(name, False, "insensitive").replace(".", "").split())
