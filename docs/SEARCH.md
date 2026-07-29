# Scripture search

## Basic search

```python
from getbible import GetBible


bible = GetBible()
response = bible.search("faith hope", "kjv")
```

The default requires every query word, performs case-insensitive whole-word matching, searches every available book, returns canonical order, and returns at most 100 matches from offset zero.

Use `search_json()` when an encoded response is required:

```python
encoded = bible.search_json("faith hope", "kjv")
```

## JSON-friendly criteria

`SearchBible` and plain dictionaries use the same field names.

`SearchBible` is the canonical public class name. `SearchCriteria` remains available as a compatibility alias for integrations that adopted the earlier development name.

`SearchBible.expensive` is available immediately after parsing, before a
translation is loaded. Public endpoints should use it to select the strict
rate tier. It is true for substring, phrase, any-word, proximity, relevance,
exclusion, insensitive-diacritic, deep-offset, and large-page criteria.

| Field | Values | Default |
|---|---|---|
| `words` | `all`, `any`, `phrase` | `all` |
| `match` | `whole_word`, `substring` | `whole_word` |
| `case_sensitive` | Boolean | `false` |
| `scope` | `bible`, `old_testament`, `new_testament`, `deuterocanon` | `bible` |
| `books` | Book names or numbers | Empty |
| `diacritics` | `sensitive`, `insensitive` | `sensitive` |
| `exclude` | Words that must not occur | Empty |
| `proximity` | 0–100 intervening words | `null` |
| `sort` | `canonical`, `relevance` | `canonical` |
| `limit` | 1–1000 | `100` |
| `offset` | Non-negative integer | `0` |

```python
from getbible import GetBible, SearchBible


bible = GetBible()
criteria = SearchBible(
    words="all",
    match="whole_word",
    case_sensitive=False,
    scope="new_testament",
    books=("John", "1 John"),
    diacritics="insensitive",
    exclude=("darkness",),
    proximity=5,
    sort="relevance",
    limit=20,
    offset=0,
)
response = bible.search("word life", "kjv", criteria)
```

`books` intersects with `scope`. For example, `scope="new_testament"` and `books=("John",)` searches only John.

## Word modes

### All words

Every distinct query term must occur in the verse:

```python
criteria = SearchBible(words="all")
response = bible.search("faith hope", "kjv", criteria)
```

### Any word

At least one query term must occur:

```python
criteria = SearchBible(words="any")
response = bible.search("faith hope", "kjv", criteria)
```

### Phrase

Terms must occur in order and adjacent, with punctuation and whitespace allowed between whole words:

```python
criteria = SearchBible(words="phrase")
response = bible.search("in the beginning", "kjv", criteria)
```

With `match="substring"`, phrase matching uses the normalized literal query.

## Whole-word and substring matching

Whole-word matching uses Unicode letter, combining-mark, and number boundaries. It supports accented Latin text, Greek, Hebrew combining marks, and other API scripts more correctly than ASCII word boundaries.

Substring matching searches inside normalized tokens. For example, `great` can match `greatest`.

The distinction remains explicit and deterministic: Librarian never silently
rewrites a requested `whole_word` search. For languages that do not reliably
separate words with spaces, applications should select `substring`.

Librarian permits one- and two-grapheme substring terms only when the complete
term uses Han, Japanese kana, Hangul, or a Unicode complex-context script such
as Thai, Lao, Khmer, or Myanmar. The configured minimum remains in force for
Latin, Arabic, Hebrew, Devanagari, Greek, Cyrillic, and other normally
space-delimited scripts. Mixed short tokens such as `a神` are rejected.

Applications can share Librarian's Unicode-property detector instead of
maintaining character ranges:

```python
from getbible import requires_substring_matching


match = (
    "substring"
    if requires_substring_matching(query)
    else "whole_word"
)
```

Use that automatic choice only when the caller has not explicitly selected a
match mode. For a query mixing continuous-writing and space-delimited terms,
keep the choice explicit: applying substring matching to the entire query also
allows partial matches for its Latin or other space-delimited terms.

Substring occurrence counts and relevance scores include every non-overlapping
occurrence inside a token. Join controls (ZWNJ and ZWJ) remain part of the
surrounding Arabic-script or Indic token instead of creating false word
boundaries.

## Case and diacritics

Case-insensitive matching uses Unicode `casefold()`. Original verse text is never modified in the response.

Diacritic-insensitive matching decomposes Unicode characters and removes combining marks from the search index. This can make `Cafe` match `Café` and can ignore Hebrew vowel marks. It does not perform transliteration.

This option is never enabled automatically. Some scripts, including
Devanagari and Southeast Asian scripts, use combining marks structurally, so
callers should request insensitive matching only when it is appropriate for
the selected translation.

## Testament and book scopes

- Old Testament: book numbers 1–39.
- New Testament: book numbers 40–66.
- Deuterocanonical or Apocryphal books: book numbers 67 and above.
- Whole Bible: every book present in the selected translation.

Book names first resolve against the official names in the selected translation, then through Librarian's bundled alias tries.

## Exclusions and proximity

`exclude` removes any verse containing one of the supplied words under the selected match mode.

`proximity` is available with `words="all"`. A value of zero requires the terms to occupy an adjacent token window; larger values permit that number of intervening words.

## Pagination and ordering

The engine always calculates the exact total before returning the selected page.

Canonical ordering follows API book, chapter, and verse order. Relevance ordering uses the number of matched occurrences, with canonical order as the stable tie-breaker.

## Response contract

```text
query
  text
  criteria
  engine_version
  translation
  sha
  total
  offset
  limit
  returned
  has_more
  cache
  cost
    work_units
    deadline_seconds
    expensive
results
  <translation>_<book>_<chapter>
    translation metadata
    book and chapter metadata
    ref
    verses
matches
  reference
  book_nr
  chapter
  verse
  score
  occurrences
  terms
```

`results` is intentionally the same grouped scripture structure returned by `select()`. Search-specific information remains in `query` and `matches`, allowing existing scripture templates to render search results.

`matches` preserves global search order. This is especially important for relevance sorting because `results` groups verses by chapter.

The `sha` field identifies the exact full-translation payload used for the search, enabling downstream response-cache invalidation.

`engine_version` identifies result-affecting search semantics independently of
the translation SHA. Search response caches should include both values in
their namespace and must be flushed when upgrading from an implementation that
did not include the engine version. `SEARCH_ENGINE_VERSION` exports the same
integer for cache-key construction before a search executes.

`cost.work_units` is the deterministic estimate enforced by
`SearchLimits.max_work_units`; it is suitable for aggregate metrics but is not
wall-clock time. `deadline_seconds` reports the cooperative library deadline,
and `expensive` mirrors the pre-execution rate-tier classification. The exact
serialized response size is enforced internally but is not echoed because a
size field would itself change the serialized size.

## Legacy criteria notation

The previously introduced compact notation remains accepted for compatibility:

```python
response = bible.search(
    "faith hope",
    "kjv",
    "allwords-exactmatch-caseinsensitive-newtestament",
)
```

New integrations should use `SearchBible` or a dictionary because they support pagination, multiple books, exclusion, proximity, and future additive fields.

## Synonyms

Automatic synonyms are deliberately not part of the initial search contract. Synonyms are translation- and language-specific and should later be added through an explicit caller-supplied query-expansion interface rather than an implicit network or AI dependency.
