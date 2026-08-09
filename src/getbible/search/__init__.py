"""Scripture search: criteria, script-aware analysis, indexing and execution.

The engine is being split out of a single module. :mod:`analysis` already
carries the script-aware tokenization that removes the caller-side matching
decision; :mod:`engine` still carries criteria, budgets, corpora and execution
and is being decomposed behind these exports. Import from this package rather
than from its submodules so the remaining moves stay internal.
"""

from __future__ import annotations

from .analysis import (
    Analyzer,
    ScriptFamily,
    Token,
    analyzer_for,
    classify_text,
    fold_marks,
    script_census,
)
from .engine import (
    SEARCH_ENGINE_VERSION,
    SearchBible,
    SearchBudget,
    SearchCriteria,
    SearchEngine,
    SearchHit,
    SearchIndex,
    SearchLimits,
    TranslationCorpus,
    VerseRecord,
    allows_short_substring,
    normalize_book_name,
    normalize_text,
    requires_substring_matching,
    validate_search_request,
)

__all__ = [
    "SEARCH_ENGINE_VERSION",
    "Analyzer",
    "ScriptFamily",
    "SearchBible",
    "SearchBudget",
    "SearchCriteria",
    "SearchEngine",
    "SearchHit",
    "SearchIndex",
    "SearchLimits",
    "Token",
    "TranslationCorpus",
    "VerseRecord",
    "allows_short_substring",
    "analyzer_for",
    "classify_text",
    "fold_marks",
    "normalize_book_name",
    "normalize_text",
    "requires_substring_matching",
    "script_census",
    "validate_search_request",
]
