# Scripture search

## The short version

Pass a query string. Librarian works out how to read it.

```python
from getbible import GetBible


bible = GetBible()

bible.search("faith hope", "kjv")
bible.search("神爱世人", "cus")      # Chinese, no spaces to tokenize
bible.search("사랑", "korean")        # Korean, inside an inflected word
bible.search("בראשית", "modernhebrew")  # unpointed, reaches pointed text
bible.search("λογος", "moderngreek")    # unaccented, reaches accented text
```

There is no match mode to choose, no script to detect, and no per-language
branch to write. If you are carrying code that inspects a query and picks
`match="substring"`, delete it — see [Migrating from 1.x](#migrating-from-1x).

The criteria that remain exist to *narrow* a search — a testament, a book, an
exclusion. They do not tell the engine how to read a script.

## How matching is decided

Librarian classifies every run of text by the writing system it is actually in,
and applies that system's rules. The same rules run over the corpus at index
time and over your query at request time, so a query can only match what the
same analysis produced from the verse.

| Family | Scripts | How a searchable unit is found |
|---|---|---|
| Alphabetic | Latin, Cyrillic, Greek, Armenian, Georgian, Coptic, Cherokee | Words between spaces. Accents fold. |
| Continuous | Han, Hiragana, Katakana, Hangul, Thai, Lao, Khmer, Myanmar, Tibetan | Overlapping character n-grams with positions. |
| Abjad | Hebrew, Arabic, Syriac, Thaana, Samaritan | Words between spaces. Vowel pointing folds. A word behind an attached particle is also reachable by its stem. |
| Brahmic | Devanagari, Bengali, Tamil, Telugu, Kannada, Malayalam, Sinhala | Words between spaces. Combining marks are **kept** — they carry vowels. |

Classification is by Unicode property, not by a hand-maintained range table and
not by the translation's declared language tag. That matters because the tag is
not always sufficient: the API carries `zh` with no script subtag for one
Chinese translation, and blank language names for several others. A translation
added to the API later is classified from its text, with no code change here.

The response reports the decision so you never have to infer it:

```python
bible.search("神", "cus")["query"]["analysis"]
# {'script': 'continuous'}
```

### Mixed scripts

A verse or a query may hold more than one writing system. Each run keeps its own
rules:

```python
bible.search("Jesus 耶稣", "multi")
# 'jesus' is matched as a whole Latin word; '耶稣' as a Han run
```

This is why the 1.x helper had to go. It flipped the *whole* query to substring
as soon as it saw one Han character, so `all` started matching inside `small`
and `shall`.

### Why whole-word and substring agree in continuous scripts

Nothing in Han, kana, Hangul or Thai delimits a word, so there is no boundary
for the two modes to disagree about. Both resolve the same way and both are
exact. A caller cannot get this wrong by choosing either.

A run of *n* characters is verified through its *n−1* overlapping bigrams: if
bigram *i* sits at position *p+i* for every *i*, the run occurs at *p*. Positions
settle it, so no verse text is rescanned and there are no false positives to
filter. `神造` does not match `神神创造神` — the characters are present, the run
is not.

## Criteria

`SearchBible` and plain dictionaries use the same field names. Every field is
optional.

| Field | Values | Default |
|---|---|---|
| `words` | `all`, `any`, `phrase` | `all` |
| `match` | `whole_word`, `substring` | `whole_word` |
| `case_sensitive` | Boolean | `false` |
| `scope` | `bible`, `old_testament`, `new_testament`, `deuterocanon` | `bible` |
| `books` | Book names or numbers | Empty |
| `diacritics` | `fold`, `exact` | `fold` |
| `exclude` | Words that must not occur | Empty |
| `proximity` | 0–100 intervening units | `null` |
| `sort` | `canonical`, `relevance` | `canonical` |
| `limit` | 1–1000 | `100` |
| `offset` | Non-negative integer | `0` |

```python
from getbible import GetBible, SearchBible


bible = GetBible()
response = bible.search(
    "word life",
    "kjv",
    SearchBible(
        words="all",
        scope="new_testament",
        books=("John", "1 John"),
        exclude=("darkness",),
        sort="relevance",
        limit=20,
    ),
)
```

`books` intersects with `scope`: `scope="new_testament"` with `books=("John",)`
searches only John.

Criteria may also be a JSON-decoded dictionary, which is what the HTTP service
passes:

```python
bible.search("faith hope", "kjv", {"words": "phrase", "limit": 50})
```

### Word modes

- **`all`** (default): every distinct unit must occur in the verse.
- **`any`**: at least one unit must occur.
- **`phrase`**: units must occur in order at the spacing the query used.
  Punctuation between them is allowed. Because a continuous run occupies one
  position per character and a word occupies one, a phrase that crosses scripts
  is handled by the same arithmetic.

### Whole-word and substring

`whole_word` matches complete units. `substring` also matches inside a word, so
`great` reaches `greatest`.

In continuous scripts the two are identical, as described above.

Substring terms in **space-delimited** scripts must be at least
`min_substring_length` characters (3 by default). A one- or two-letter Latin
fragment matches a large share of any vocabulary and is a scan rather than a
word. The floor does not apply to Han, Hangul, Thai, Hebrew, Arabic or
Devanagari, where two characters are an ordinary word that the index answers
exactly. In a mixed query the floor still applies to the Latin run alone.

### Case and diacritics

Case-insensitive matching uses Unicode `casefold()`, which also unifies Greek
final and medial sigma (ς/σ) and expands the iota subscript. Both sides of a
search pass through the same rule, so the forms meet.

`diacritics="fold"` is the default. It removes combining marks and folds
precomposed letters that Unicode decomposition cannot reach — `đ`, `ø`, `ł`,
`ħ`, `æ`, `þ` and peers. That is what lets `Duc Chua Troi` reach
`Ðức Chúa Trời`, `λογος` reach `λόγος`, and `בראשית` reach `בְּרֵאשִׁית`.

Folding is applied only where marks are accents or optional pointing. Brahmic
and continuous scripts keep their marks, because there the marks carry vowels
and removing them changes the word.

`diacritics="exact"` turns folding off and distinguishes pointed from unpointed
text. The 1.x spellings `sensitive` and `insensitive` are still accepted and map
to `exact` and `fold`.

Original verse text is never modified in the response.

### Exclusions and proximity

`exclude` removes any verse containing one of the supplied words, analysed the
same way as the query. `proximity` works with `words="all"` and permits that
many intervening units.

## Response contract

`results` is the same chapter-keyed object `select()` returns, so existing
scripture templates keep working. `matches` is the authoritative order when
sorting by relevance.

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
    checked_at
    stale
  analysis
    script            ← how this translation was read
  cost
    work_units
    deadline_seconds
    expensive
results
  <translation>_<book>_<chapter>
    translation, book and chapter metadata
    ref
    verses
matches
  reference, book_nr, chapter, verse
  score, occurrences, terms
```

`engine_version` is `4`. It moves whenever matching semantics change, so a
downstream result cache can be invalidated without waiting for a translation SHA
to change. **Key your response cache on it.**

`SearchBible.expensive` is available before a translation is loaded and is the
right signal for a strict rate tier. Diacritic folding is no longer part of it:
folding happens once during index construction and costs nothing per request.

## Performance and sharing

Corpora live in a registry keyed by repository, translation and source SHA, and
are shared by every `GetBible` in the process. Two clients — or a client per
request — reach the same parsed verses and the same analysed index, so a service
pays the parse-and-analyse cost once per translation version rather than once
per object.

```python
bible.warm_translation("cus")   # build before traffic; returns the analysis report
```

An index build is bounded by `SearchLimits.index_build_seconds` (120 s default),
not by the requesting call's `deadline_seconds`. A build serves every later
request, so it must not be abandoned because one caller's request clock ran out.
Concurrent first requests wait on one build rather than each starting their own.

A search still refuses an unusable work budget before any index is built.

## Migrating from 1.x

### Delete the match-mode selection

```python
# 1.x — remove this
from getbible import requires_substring_matching

if options.match == "whole_word" and requires_substring_matching(query):
    options = replace(options, match="substring")
```

`requires_substring_matching()` now returns `False` for every query. It remains
exported so existing imports keep working and the branch above becomes a no-op
without an immediate code change — but delete it. Leaving it in place is
harmless; leaving *substring* forced on is not, because it loosens Latin terms
in a mixed query.

### Behaviour that changes

| | 1.x | 2.0 |
|---|---|---|
| Continuous scripts under default criteria | returned nothing | return the verses |
| `diacritics` default | `sensitive` | `fold` |
| Substring floor | all scripts | space-delimited scripts only |
| `engine_version` | `2` | `4` |
| Abjad with attached particle | missed | reachable by stem |

Default searches return **more** than they did. If your application asserted a
1.x total, re-derive it. Invalidate any cached search results — `engine_version`
is there to key that on.

### API that changed shape

- `cache_info()["indexes"]` entries report `fold_diacritics` (boolean) instead
  of `diacritics` (string).
- `warm_translation()` takes `diacritics="fold"` by default and returns an
  `analysis` block.
- `SEARCH_ENGINE_VERSION` is `4`.
- `getbible.search` is a package. Every public name still imports from
  `getbible` and from `getbible.search`; the internal `_Matcher` class is gone.

`select()`, `scripture()`, and the `results` structure are unchanged.
