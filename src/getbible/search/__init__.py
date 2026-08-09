"""Scripture search: criteria, script-aware analysis, indexing and execution.

Import from this package rather than from its submodules. The public names are
stable; where they live inside the package is not.

The engine derives its matching strategy from the text of the translation and
of the query, so an application supplies a query string and, at most, filters
that narrow the search. It never has to decide how a script should be read.
"""

from __future__ import annotations

from .analysis import (
    Analyzer,
    ScriptFamily,
    Token,
    analyzer_for,
    casefold_text,
    classify_text,
    continuous_chain,
    fold_marks,
    normalize_book_name,
    normalize_text,
    script_census,
)
from .corpus import CorpusRegistry, TranslationCorpus, VerseRecord, shared_registry
from .criteria import SearchBible, SearchCriteria
from .engine import (
    SEARCH_ENGINE_VERSION,
    QueryUnit,
    SearchEngine,
    SearchHit,
    allows_short_substring,
    analyze_query,
    requires_substring_matching,
    validate_search_request,
)
from .index import Postings, SearchIndex, build_index, chain_matches
from .limits import SearchBudget, SearchLimits

__all__ = [
    "SEARCH_ENGINE_VERSION",
    "Analyzer",
    "CorpusRegistry",
    "Postings",
    "QueryUnit",
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
    "analyze_query",
    "analyzer_for",
    "build_index",
    "casefold_text",
    "chain_matches",
    "classify_text",
    "continuous_chain",
    "fold_marks",
    "normalize_book_name",
    "normalize_text",
    "requires_substring_matching",
    "script_census",
    "shared_registry",
    "validate_search_request",
]
