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

## Case and diacritics

Case-insensitive matching uses Unicode `casefold()`. Original verse text is never modified in the response.

Diacritic-insensitive matching decomposes Unicode characters and removes combining marks from the search index. This can make `Cafe` match `Café` and can ignore Hebrew vowel marks. It does not perform transliteration.

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
  translation
  sha
  total
  offset
  limit
  returned
  has_more
  cache
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
