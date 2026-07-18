# HTTP GET endpoint integration

Librarian is a Python library and does not start an HTTP server. The GetBible
Query service is the HTTP boundary and should expose search as a read-only GET
operation:

```text
GET /v2/search/{translation}?q={query}
```

For example:

```bash
curl --get 'https://query.getbible.net/v2/search/kjv' \
  --data-urlencode 'q=faith hope' \
  --data 'words=all' \
  --data 'match=whole_word' \
  --data 'scope=new_testament' \
  --data 'limit=25'
```

No request body or POST operation is required. `q` is the only required query
parameter. Omitted filters use `SearchBible` defaults.

## Query parameter mapping

| URL parameter | `SearchBible` field | Accepted values | Default |
|---|---|---|---|
| `q` | Search method argument | Non-empty text | Required |
| `words` | `words` | `all`, `any`, `phrase` | `all` |
| `match` | `match` | `whole_word`, `substring` | `whole_word` |
| `case_sensitive` | `case_sensitive` | `true`, `false` | `false` |
| `scope` | `scope` | `bible`, `old_testament`, `new_testament`, `deuterocanon` | `bible` |
| `book` | `books` | Repeatable book name or number | All books |
| `books` | `books` | Comma-separated names or numbers | All books |
| `diacritics` | `diacritics` | `sensitive`, `insensitive` | `sensitive` |
| `exclude` | `exclude` | Repeatable excluded term | None |
| `proximity` | `proximity` | Integer from 0 through 100 | None |
| `sort` | `sort` | `canonical`, `relevance` | `canonical` |
| `limit` | `limit` | Public-service bounded positive integer | `100` |
| `offset` | `offset` | Public-service bounded non-negative integer | `0` |

Use repeated parameters where delimiters could be ambiguous:

```text
/v2/search/kjv?q=faith&book=Genesis&book=Matthew&exclude=darkness
```

The service layer should reject unknown parameters, invalid booleans and
integers, overlong input, and public pagination values above its own limits
before calling Librarian. It should URL-decode parameters exactly once and pass
a normal dictionary containing only the supplied, validated filters to the
library:

```python
criteria = SearchBible.from_value(validated_filter_values)
response = bible.search(request.args["q"], translation, criteria)
```

Do not pass raw query values through Python truthiness (`bool("false")` is
`True`), silently ignore unknown filters, or expose regular expressions.

## Response and caching

Return `bible.search()` directly as JSON. Its `results` object retains the same
chapter-keyed Scripture structure as `select()`; `query` and `matches` are the
additive search layers.

Keep public response-cache lifetimes shorter than Librarian's repository
freshness interval. The response `query.sha` identifies the exact translation
payload, while `query.cache.stale` lets the service observe last-known-good
fallbacks. HTTP response caching must vary on the complete normalized query
string, including repeated parameters.
