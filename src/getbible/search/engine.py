"""Query execution against an analysed translation.

The engine never asks the caller how to read a script. A query is passed
through the same analyser that built the index, which turns it into *units*:
one unit per word in a space-delimited script, one per uninterrupted run in a
continuous script. Units are then resolved through positional postings, so
"which verses contain this" is answered the same way in every writing system
and costs what the result set costs rather than what the vocabulary costs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from ..exceptions import SearchLimitError, SearchValidationError
from .analysis import Analyzer, ScriptFamily, Token, continuous_chain, normalize_text
from .corpus import TranslationCorpus, VerseRecord
from .criteria import SearchBible
from .index import SearchIndex, chain_matches
from .limits import SearchBudget, SearchLimits

__all__ = [
    "SEARCH_ENGINE_VERSION",
    "QueryUnit",
    "SearchEngine",
    "SearchHit",
    "analyze_query",
    "validate_search_request",
]

#: Bumped whenever matching semantics change, so a downstream result cache can
#: be invalidated without waiting for a translation SHA to move.
SEARCH_ENGINE_VERSION = 3


@dataclass(frozen=True, slots=True)
class SearchHit:
    record: VerseRecord
    score: int
    occurrences: int
    terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QueryUnit:
    """One thing the reader asked for, in the form the index stores it."""

    text: str
    tokens: tuple[Token, ...]
    family: ScriptFamily
    offset: int
    span: int

    @property
    def continuous(self) -> bool:
        return self.family is ScriptFamily.CONTINUOUS


def analyze_query(analyzer: Analyzer, query: str) -> tuple[QueryUnit, ...]:
    """Split a query into units using the writing system of each part.

    A query mixing scripts yields units of different kinds, each carrying the
    rules of its own script. That is what stops one Han character from turning
    a whole query into a substring search, which is how the previous
    caller-side helper degraded Latin terms.
    """
    units: list[QueryUnit] = []
    offset = 0
    for family, run in analyzer.runs(query):
        if family is ScriptFamily.CONTINUOUS:
            chain = continuous_chain(run)
            span = len(run)
            units.append(QueryUnit(run, chain, family, offset, span))
            offset += span
        else:
            units.append(
                QueryUnit(run, (Token(run, 0, family),), family, offset, 1)
            )
            offset += 1
    return tuple(units)


def validate_search_request(
    query: object,
    criteria: SearchBible,
    limits: SearchLimits,
) -> tuple[str, tuple[QueryUnit, ...], tuple[tuple[QueryUnit, ...], ...]]:
    """Validate every corpus-independent limit before repository access."""
    if not isinstance(query, str):
        raise SearchValidationError("Search query must be a string.")
    stripped = query.strip()
    if not stripped:
        raise SearchValidationError("Search query cannot be empty.")
    if len(stripped) > limits.max_query_length:
        raise SearchValidationError(
            f"Search query cannot exceed {limits.max_query_length} characters."
        )
    if criteria.limit > limits.max_limit:
        raise SearchLimitError(f"Search limit cannot exceed {limits.max_limit}.")
    if criteria.offset > limits.max_offset:
        raise SearchLimitError(f"Search offset cannot exceed {limits.max_offset}.")
    if len(criteria.books) > limits.max_books:
        raise SearchLimitError(
            f"Search cannot select more than {limits.max_books} books."
        )
    book_names = tuple(book for book in criteria.books if isinstance(book, str))
    if any(len(book) > limits.max_book_length for book in book_names):
        raise SearchLimitError(
            f"Search book names cannot exceed {limits.max_book_length} characters."
        )
    if sum(map(len, book_names)) > limits.max_books_length:
        raise SearchLimitError(
            "Search book names cannot contain more than "
            f"{limits.max_books_length} characters in total."
        )
    if len(criteria.exclude) > limits.max_exclusions:
        raise SearchLimitError(
            f"Search cannot contain more than {limits.max_exclusions} exclusions."
        )
    if any(len(term) > limits.max_exclusion_length for term in criteria.exclude):
        raise SearchLimitError(
            f"Search exclusions cannot exceed {limits.max_exclusion_length} characters each."
        )
    if sum(map(len, criteria.exclude)) > limits.max_exclusions_length:
        raise SearchLimitError(
            "Search exclusions cannot contain more than "
            f"{limits.max_exclusions_length} characters in total."
        )

    analyzer = Analyzer(
        case_sensitive=criteria.case_sensitive,
        fold_diacritics=criteria.fold_diacritics,
    )
    units = analyze_query(analyzer, stripped)
    if not units:
        raise SearchValidationError("Search query must contain letters or numbers.")
    if len(units) > limits.max_query_terms:
        raise SearchValidationError(
            f"Search query cannot exceed {limits.max_query_terms} terms."
        )
    if criteria.words != "phrase":
        units = tuple({unit.text: unit for unit in units}.values())

    exclusions = tuple(
        analyze_query(analyzer, term) for term in criteria.exclude
    )
    excluded_units = sum(len(group) for group in exclusions)
    if excluded_units > limits.max_exclusion_terms:
        raise SearchLimitError(
            "Search exclusions cannot contain more than "
            f"{limits.max_exclusion_terms} terms."
        )
    _validate_substring_length(criteria, limits, units, exclusions)
    return stripped, units, exclusions


def _validate_substring_length(
    criteria: SearchBible,
    limits: SearchLimits,
    units: Sequence[QueryUnit],
    exclusions: Sequence[Sequence[QueryUnit]],
) -> None:
    """Guard open-ended substring scans on space-delimited scripts only.

    A one- or two-letter Latin fragment matches inside a large share of the
    vocabulary and is rarely what a reader means. The same length in Han,
    Hangul, Thai or Hebrew is an ordinary word, so the minimum does not apply
    there — the index answers those exactly, without scanning.
    """
    if criteria.match != "substring":
        return
    everything = [*units, *(unit for group in exclusions for unit in group)]
    for unit in everything:
        if unit.family is not ScriptFamily.ALPHABETIC:
            continue
        if len(unit.text) < limits.min_substring_length:
            raise SearchValidationError(
                "Substring search terms must contain at least "
                f"{limits.min_substring_length} characters in space-delimited scripts."
            )


class SearchEngine:
    """Execute criteria against a loaded translation corpus."""

    def __init__(
        self,
        corpus: TranslationCorpus,
        book_number: Callable[[str], int | None],
        limits: SearchLimits | None = None,
    ) -> None:
        self.corpus = corpus
        self.book_number = book_number
        self.limits = limits or SearchLimits()
        self.execution_info: dict[str, int | float | bool | str] = {}

    def search(
        self,
        query: str,
        criteria: SearchBible,
    ) -> tuple[list[SearchHit], int]:
        budget = SearchBudget(self.limits)
        _, units, exclusions = validate_search_request(query, criteria, self.limits)
        book_filter = self._book_filter(criteria)
        # A search over N verses cannot cost less than N, and that floor is
        # known without touching the index. Checking it first keeps a request
        # with an unusable budget from triggering an index build.
        budget.reserve(len(self.corpus.records) + criteria.limit * 8)
        index = self.corpus.index(
            criteria.case_sensitive, criteria.fold_diacritics, self.limits
        )
        budget.reserve(self._estimate_work(index, units, exclusions, criteria))

        resolved = [self._resolve(index, unit, criteria, budget) for unit in units]
        matched = self._combine(resolved, units, criteria, budget)
        matched = self._apply_exclusions(index, matched, exclusions, criteria, budget)
        if criteria.proximity is not None:
            matched = self._apply_proximity(matched, resolved, units, criteria, budget)

        eligible = self._eligible_ordinals(book_filter, budget)
        hits: list[SearchHit] = []
        for position, (ordinal, (occurrences, terms)) in enumerate(sorted(matched.items())):
            budget.checkpoint(position)
            if eligible is not None and ordinal not in eligible:
                continue
            hits.append(
                SearchHit(
                    record=self.corpus.records[ordinal],
                    score=occurrences,
                    occurrences=occurrences,
                    terms=terms,
                )
            )

        if criteria.sort == "relevance":
            hits.sort(key=lambda hit: (-hit.score, hit.record.ordinal))
        total = len(hits)
        page = hits[criteria.offset:criteria.offset + criteria.limit]
        self._finish_execution(budget, criteria, index)
        return page, total

    def _resolve(
        self,
        index: SearchIndex,
        unit: QueryUnit,
        criteria: SearchBible,
        budget: SearchBudget,
    ) -> dict[int, list[int]]:
        """Return, per verse, the positions where this unit occurs."""
        budget.check_deadline()
        if unit.continuous:
            # Continuous scripts have no word boundary to respect, so
            # whole-word and substring resolve identically and exactly.
            return chain_matches(index, unit.tokens)
        if criteria.match == "whole_word":
            return _positions_of(index, unit.text)
        found: dict[int, list[int]] = {}
        for position, term in enumerate(index.terms_containing(unit.text)):
            budget.checkpoint(position)
            for ordinal, positions in _positions_of(index, term).items():
                found.setdefault(ordinal, []).extend(positions)
        for positions in found.values():
            positions.sort()
        return found

    def _combine(
        self,
        resolved: Sequence[dict[int, list[int]]],
        units: Sequence[QueryUnit],
        criteria: SearchBible,
        budget: SearchBudget,
    ) -> dict[int, tuple[int, tuple[str, ...]]]:
        if not resolved:
            return {}
        if criteria.words == "any":
            candidates: set[int] = set()
            for found in resolved:
                candidates |= set(found)
        else:
            candidates = set(resolved[0])
            for found in resolved[1:]:
                candidates &= set(found)
                if not candidates:
                    return {}
        if criteria.words == "phrase":
            aligned: set[int] = set()
            for position, ordinal in enumerate(sorted(candidates)):
                budget.checkpoint(position)
                if _phrase_aligned(resolved, units, ordinal):
                    aligned.add(ordinal)
            candidates = aligned

        matched: dict[int, tuple[int, tuple[str, ...]]] = {}
        for position, ordinal in enumerate(sorted(candidates)):
            budget.checkpoint(position)
            present = tuple(
                unit.text
                for unit, found in zip(units, resolved, strict=True)
                if ordinal in found
            )
            if criteria.words == "phrase":
                occurrences = _phrase_occurrences(resolved, units, ordinal)
            else:
                occurrences = sum(
                    len(found.get(ordinal, ())) for found in resolved
                )
            if occurrences:
                matched[ordinal] = (occurrences, present)
        return matched

    def _apply_exclusions(
        self,
        index: SearchIndex,
        matched: dict[int, tuple[int, tuple[str, ...]]],
        exclusions: Sequence[Sequence[QueryUnit]],
        criteria: SearchBible,
        budget: SearchBudget,
    ) -> dict[int, tuple[int, tuple[str, ...]]]:
        if not exclusions or not matched:
            return matched
        removed: set[int] = set()
        for group in exclusions:
            for unit in group:
                removed |= set(self._resolve(index, unit, criteria, budget))
        if not removed:
            return matched
        return {
            ordinal: value
            for ordinal, value in matched.items()
            if ordinal not in removed
        }

    def _apply_proximity(
        self,
        matched: dict[int, tuple[int, tuple[str, ...]]],
        resolved: Sequence[dict[int, list[int]]],
        units: Sequence[QueryUnit],
        criteria: SearchBible,
        budget: SearchBudget,
    ) -> dict[int, tuple[int, tuple[str, ...]]]:
        allowed = int(criteria.proximity or 0)
        near: dict[int, tuple[int, tuple[str, ...]]] = {}
        for position, (ordinal, value) in enumerate(matched.items()):
            budget.checkpoint(position)
            if _within_proximity(resolved, units, ordinal, allowed):
                near[ordinal] = value
        return near

    def _eligible_ordinals(
        self, book_filter: frozenset[int], budget: SearchBudget
    ) -> frozenset[int] | None:
        if book_filter == self.corpus.available_books:
            return None
        selected: set[int] = set()
        for ordinal, record in enumerate(self.corpus.records):
            budget.checkpoint(ordinal)
            if record.book_nr in book_filter:
                selected.add(record.ordinal)
        return frozenset(selected)

    def _estimate_work(
        self,
        index: SearchIndex,
        units: Sequence[QueryUnit],
        exclusions: Sequence[Sequence[QueryUnit]],
        criteria: SearchBible,
    ) -> int:
        """Cost a search from postings lengths rather than by rehearsing it.

        The previous estimator walked the whole vocabulary for every term,
        which cost more than the search it was protecting. Postings lengths are
        already known, so the estimate is a handful of dictionary lookups.
        """
        units_cost = 0
        for unit in (*units, *(unit for group in exclusions for unit in group)):
            if unit.continuous:
                units_cost += sum(len(index.get(token.term) or ()) for token in unit.tokens)
            elif criteria.match == "substring":
                # Candidate generation is bounded by the term dictionary, but
                # only the fragment's trigram buckets are ever visited.
                units_cost += len(index.postings) // max(1, len(unit.text))
            else:
                units_cost += len(index.get(unit.text) or ())
        if criteria.sort == "relevance":
            units_cost += len(self.corpus.records).bit_length() * max(1, len(units))
        return units_cost + criteria.limit * 8 + len(units)

    def _finish_execution(
        self, budget: SearchBudget, criteria: SearchBible, index: SearchIndex
    ) -> None:
        budget.check_deadline()
        self.execution_info = {
            "engine_version": SEARCH_ENGINE_VERSION,
            "work_units": budget.work_units,
            "deadline_seconds": float(self.limits.deadline_seconds),
            "elapsed_seconds": budget.elapsed_seconds,
            "expensive": criteria.expensive,
            "script": index.dominant_family.value,
        }

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
            scoped.intersection_update(
                self.corpus.resolve_books(criteria.books, self.book_number)
            )
        return frozenset(scoped)


def _positions_of(index: SearchIndex, term: str) -> dict[int, list[int]]:
    postings = index.get(term)
    if postings is None:
        return {}
    found: dict[int, list[int]] = {}
    for offset, ordinal in enumerate(postings.ordinals):
        found.setdefault(ordinal, []).append(postings.positions[offset])
    return found


def _phrase_aligned(
    resolved: Sequence[dict[int, list[int]]],
    units: Sequence[QueryUnit],
    ordinal: int,
) -> bool:
    """Return whether the units occur in the verse at the query's spacing."""
    return bool(_phrase_starts(resolved, units, ordinal))


def _phrase_occurrences(
    resolved: Sequence[dict[int, list[int]]],
    units: Sequence[QueryUnit],
    ordinal: int,
) -> int:
    return len(_phrase_starts(resolved, units, ordinal))


def _phrase_starts(
    resolved: Sequence[dict[int, list[int]]],
    units: Sequence[QueryUnit],
    ordinal: int,
) -> list[int]:
    """Positions where the whole phrase begins in one verse.

    Each unit must sit exactly as far from the first unit as it did in the
    query. Because a continuous run occupies one position per character and a
    word occupies one, the same arithmetic spans a phrase that crosses scripts.
    """
    base = units[0].offset
    starts: set[int] | None = None
    for unit, found in zip(units, resolved, strict=True):
        positions = found.get(ordinal)
        if not positions:
            return []
        shift = unit.offset - base
        current = {position - shift for position in positions}
        starts = current if starts is None else (starts & current)
        if not starts:
            return []
    return sorted(starts or ())


def _within_proximity(
    resolved: Sequence[dict[int, list[int]]],
    units: Sequence[QueryUnit],
    ordinal: int,
    allowed: int,
) -> bool:
    """Return whether every unit fits inside one window in this verse."""
    groups = [found.get(ordinal) or [] for found in resolved]
    if any(not group for group in groups):
        return False
    span = sum(unit.span for unit in units)
    for start in groups[0]:
        lower = upper = start
        chosen = True
        for group in groups[1:]:
            nearest = min(group, key=lambda value: abs(value - start))
            lower = min(lower, nearest)
            upper = max(upper, nearest)
            if upper - lower + 1 - span > allowed:
                chosen = False
                break
        if chosen:
            return True
    return False


def merged_terms(units: Iterable[QueryUnit]) -> tuple[str, ...]:
    return tuple(unit.text for unit in units)


def requires_substring_matching(query: str) -> bool:
    """Deprecated. Always ``False``.

    Kept so existing integrations keep importing successfully. Continuous
    scripts no longer need a caller-selected match mode: the engine analyses
    every script correctly under the default criteria, so an application that
    still calls this now receives an answer that leaves its search unchanged.
    Delete the call.
    """
    if not isinstance(query, str):
        raise TypeError("query must be a string.")
    return False


def allows_short_substring(term: str) -> bool:
    """Deprecated. Reports whether the substring minimum is waived for a term."""
    if not isinstance(term, str):
        raise TypeError("term must be a string.")
    analyzer = Analyzer()
    runs = analyzer.runs(term)
    return bool(runs) and all(
        family is not ScriptFamily.ALPHABETIC for family, _ in runs
    )


__all__ += [
    "allows_short_substring",
    "merged_terms",
    "normalize_text",
    "requires_substring_matching",
]
