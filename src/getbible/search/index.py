"""Positional postings built from script-aware analysis.

The previous index stored, for each token, the verses it appeared in. That is
enough to answer "which verses contain this word" for scripts where a word is a
run of letters between spaces, and useless everywhere else: in Han or Thai the
whole clause is one token, so the postings key is a clause and no query ever
equals one.

Here every token carries its position in the verse, and continuous scripts are
indexed as overlapping character n-grams. A multi-character Han query is then
answered by intersecting the postings of its bigrams and checking that their
positions are consecutive, which is exact — no text rescan, no false positives,
and cost proportional to how many verses match rather than to vocabulary size.
"""

from __future__ import annotations

import threading
from array import array
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Final

from .._memory import estimated_bytes
from .analysis import Analyzer, ScriptFamily, Token, script_census

__all__ = ["Postings", "SearchIndex", "build_index", "chain_matches", "merge_verses"]

_TRIGRAM: Final = 3


@dataclass(frozen=True, slots=True)
class Postings:
    """Verse ordinals and in-verse positions for one index term.

    Both arrays share an index: entry ``i`` says the term occurs in verse
    ``ordinals[i]`` at position ``positions[i]``. Entries are appended in verse
    order and, within a verse, in position order, so both are already sorted
    for merge-style intersection.
    """

    ordinals: array
    positions: array

    def __len__(self) -> int:
        return len(self.ordinals)

    def verses(self) -> Iterator[int]:
        """Yield each distinct verse ordinal once, in ascending order."""
        previous = -1
        for ordinal in self.ordinals:
            if ordinal != previous:
                previous = ordinal
                yield ordinal

    def verse_set(self) -> set[int]:
        return set(self.ordinals)

    def positions_in(self, ordinal: int) -> list[int]:
        """Return the positions this term occupies inside one verse."""
        found: list[int] = []
        for index, value in enumerate(self.ordinals):
            if value == ordinal:
                found.append(self.positions[index])
            elif found:
                break
        return found


@dataclass(slots=True)
class SearchIndex:
    """One analysed view of a translation, ready to answer queries."""

    analyzer: Analyzer
    texts: tuple[str, ...]
    postings: dict[str, Postings]
    document_frequency: dict[str, int]
    families: dict[ScriptFamily, int]
    build_work_units: int
    _trigrams: dict[str, list[str]] | None = field(default=None, repr=False)

    _base_bytes: int = field(default=0, init=False, repr=False)
    _trigram_bytes: int = field(default=0, init=False, repr=False)
    _trigram_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._base_bytes = estimated_bytes((
            self.analyzer, self.texts, self.postings, self.document_frequency, self.families,
        ))

    @property
    def estimated_bytes(self) -> int:
        return self._base_bytes + self._trigram_bytes

    def get(self, term: str) -> Postings | None:
        return self.postings.get(term)

    def frequency(self, term: str) -> int:
        return self.document_frequency.get(term, 0)

    @property
    def dominant_family(self) -> ScriptFamily:
        return max(self.families, key=lambda family: self.families[family])

    def analysis_report(self) -> dict[str, object]:
        """Describe how this translation was analysed, for the response."""
        total = sum(self.families.values()) or 1
        return {
            "dominant_script": self.dominant_family.value,
            "scripts": {
                family.value: round(count / total, 4)
                for family, count in self.families.items()
                if count
            },
            "case_sensitive": self.analyzer.case_sensitive,
            "fold_diacritics": self.analyzer.fold_diacritics,
            "terms": len(self.postings),
        }

    def terms_containing(self, fragment: str) -> Iterator[str]:
        """Yield index terms containing ``fragment``, via a trigram filter.

        Substring matching used to compare every vocabulary entry against every
        query term. Trigram candidate generation replaces that linear scan: only
        terms sharing all of the fragment's trigrams are examined, so a
        substring search costs about what a whole-word search costs plus the
        verification of a small candidate set.
        """
        if len(fragment) < _TRIGRAM:
            for term in self.postings:
                if fragment in term:
                    yield term
            return
        table = self._trigram_table()
        grams = {fragment[i:i + _TRIGRAM] for i in range(len(fragment) - _TRIGRAM + 1)}
        buckets = [table.get(gram) for gram in grams]
        if any(bucket is None for bucket in buckets):
            return
        buckets.sort(key=len)
        candidates = set(buckets[0])
        for bucket in buckets[1:]:
            candidates.intersection_update(bucket)
            if not candidates:
                return
        for term in candidates:
            if fragment in term:
                yield term

    def _trigram_table(self) -> dict[str, list[str]]:
        with self._trigram_lock:
            table = self._trigrams
            if table is None:
                table = {}
                for term in self.postings:
                    if len(term) < _TRIGRAM:
                        continue
                    for index in range(len(term) - _TRIGRAM + 1):
                        table.setdefault(term[index:index + _TRIGRAM], []).append(term)
                self._trigram_bytes = estimated_bytes(table)
                self._trigrams = table
            return table


def build_index(
    texts: Sequence[str],
    analyzer: Analyzer,
    checkpoint: object = None,
) -> SearchIndex:
    """Analyse every verse once and collect positional postings.

    ``checkpoint`` is an optional callable invoked with the verse ordinal so a
    caller can observe progress. It is deliberately not a deadline: an index is
    built once per translation and must not be abandoned part-way, because a
    half-built index that is never cached makes the next request repeat the same
    work and fail the same way.
    """
    prepared: list[str] = []
    ordinals: dict[str, array] = {}
    positions: dict[str, array] = {}
    frequency: dict[str, int] = {}
    work = 0

    for ordinal, text in enumerate(texts):
        if checkpoint is not None:
            checkpoint(ordinal)
        value = analyzer.prepare(text)
        prepared.append(value)
        tokens = analyzer.tokens(text)
        work += len(value) + len(tokens)
        seen: set[str] = set()
        for token in tokens:
            term = token.term
            ordinal_list = ordinals.get(term)
            if ordinal_list is None:
                ordinal_list = ordinals[term] = array("I")
                positions[term] = array("I")
            ordinal_list.append(ordinal)
            positions[term].append(token.position)
            if term not in seen:
                seen.add(term)
                frequency[term] = frequency.get(term, 0) + 1

    postings = {
        term: Postings(ordinals=values, positions=positions[term])
        for term, values in ordinals.items()
    }
    return SearchIndex(
        analyzer=analyzer,
        texts=tuple(prepared),
        postings=postings,
        document_frequency=frequency,
        families=script_census(texts),
        build_work_units=work,
    )


def chain_matches(
    index: SearchIndex,
    tokens: Sequence[Token],
) -> dict[int, list[int]]:
    """Resolve one continuous-script run to the verses and positions it starts at.

    A run of ``n`` characters is verified through its ``n - 1`` overlapping
    bigrams: if bigram ``i`` sits at position ``p + i`` for every ``i``, the run
    occurs at ``p``. Positions alone prove the match, so no verse text is read.
    """
    if not tokens:
        return {}
    if len(tokens) == 1:
        found = index.get(tokens[0].term)
        if found is None:
            return {}
        matched: dict[int, list[int]] = {}
        for offset, ordinal in enumerate(found.ordinals):
            matched.setdefault(ordinal, []).append(found.positions[offset])
        return matched

    base = tokens[0].position
    candidates: dict[int, set[int]] | None = None
    for token in tokens:
        found = index.get(token.term)
        if found is None:
            return {}
        shift = token.position - base
        current: dict[int, set[int]] = {}
        for offset, ordinal in enumerate(found.ordinals):
            current.setdefault(ordinal, set()).add(found.positions[offset] - shift)
        if candidates is None:
            candidates = current
            continue
        merged: dict[int, set[int]] = {}
        for ordinal, starts in current.items():
            previous = candidates.get(ordinal)
            if previous is None:
                continue
            shared = previous & starts
            if shared:
                merged[ordinal] = shared
        candidates = merged
        if not candidates:
            return {}
    return {
        ordinal: sorted(starts)
        for ordinal, starts in (candidates or {}).items()
    }


def merge_verses(groups: Iterable[Iterable[int]]) -> set[int]:
    """Intersect verse-ordinal groups, returning empty when any group is empty."""
    result: set[int] | None = None
    for group in groups:
        current = set(group)
        if not current:
            return set()
        result = current if result is None else (result & current)
        if not result:
            return set()
    return result or set()

