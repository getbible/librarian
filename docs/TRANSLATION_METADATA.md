# Translation metadata and the 3.0 migration

## Response field contract

Librarian 3.0 deliberately limits translation metadata in reference and search
results to the fields used by API v2 chapter responses, such as
[Genesis 1 in the KJV](https://api.getbible.net/v2/kjv/1/1.json).

| Field | Meaning | KJV value |
|---|---|---|
| `translation` | Full translation name | `King James Version` |
| `abbreviation` | API translation identifier | `kjv` |
| `lang` | Short language code supplied by the API | `en` |
| `language` | Full language label supplied by the API | `English` |
| `direction` | Text direction | `LTR` |
| `encoding` | Text encoding label | `UTF-8` |

The KJV translation metadata is:

```json
{
  "translation": "King James Version",
  "abbreviation": "kjv",
  "lang": "en",
  "language": "English",
  "direction": "LTR",
  "encoding": "UTF-8"
}
```

These are the only allowed translation keys. The projection preserves source
values without renaming fields, shortening language labels, normalizing their
contents, or inventing defaults. Existing source validation still applies:
optional fields omitted by a valid source remain absent, and accepted empty
values remain empty. A translation name is always `translation`; the chapter's
`name` still means its chapter name.

## Where the projection applies

| Public result | Translation metadata location |
|---|---|
| `select(reference, translation)` | Top level of each chapter under its existing chapter key |
| `scripture(reference, translation)` | The same chapter objects, encoded as JSON |
| `search(query, translation)` | `query.translation` and the top level of every chapter in `results` |
| `search_json(query, translation)` | The same search envelope, encoded as JSON |

For example, `select("Genesis 1:1", "kjv")["kjv_1_1"]` combines those
translation fields with the existing `book_nr`, `book_name`, `chapter`, `name`,
`ref`, and `verses` fields. In a search,
`response["query"]["translation"]["translation"]` is the full translation
name; `response["query"]["translation"]["abbreviation"]` is its identifier.

The same contract applies to direct chapter reads, retained chapters, and
chapters populated by `warm_query()` or `reload_translation()`. Empty searches
and pages beyond the final result still include the projected
`query.translation`; their `results` and `matches` remain empty.

The chapter-keyed dictionary, book/chapter identity, references, and complete
verse dictionaries retain their existing structure. Search keeps its `query`,
`results`, and `matches` envelope, including criteria, totals, pagination,
matching details, source SHA, cache state, analysis, and cost metadata. The
projection does not change matching or verse text.

## Complete translation metadata

Translation history, descriptions, distribution/license data, source details,
and every other supplemental translation field are excluded from query and
search responses. Fetch the existing
[API translation catalogue](https://api.getbible.net/v2/translations.json)
separately when those details are needed. It contains metadata for all
translations, so a client can retain that catalogue and use `abbreviation` to
associate query/search results with it. For a custom API-compatible repository,
use its corresponding catalogue if it provides one.

This is a result-assembly change. Librarian still loads and validates complete
source payloads, verifies checksums, preserves last-known-good translations,
and uses the lightweight chapter path for ordinary references. It does not
fetch the catalogue as part of a search or reference request.

## Upgrade from 2.x

Removing fields is an intentional breaking compatibility decision and the
reason for version `3.0.0`. Earlier `query.translation` copied every top-level
translation field except `books`; warmed reference chapters could carry the
same supplemental metadata. Neither pass-through behavior is part of the
3.0 contract. Do not restore it when adding source fields or changing cache
paths.

1. Keep using the six API fields at their existing locations. Consumers that
   need additional translation details should obtain the catalogue separately
   and look up the result's `abbreviation`.
2. Update response schemas, expected output, and consumers that required the
   removed fields. Do not require optional metadata omitted by a valid source
   or replace valid empty values with guessed labels.
3. Invalidate saved reference responses that contain old metadata. Include the
   package/response contract version in any application-owned reference-result
   cache key; the source SHA alone does not identify the response contract.
4. Invalidate saved search responses or key them with the exported
   `SEARCH_ENGINE_VERSION`, now `5`. Its previous value was `4`; the source SHA
   can stay the same while the response shape changes. Source-generation
   namespaces alone do not distinguish library response versions.
5. Pin `getbible==3.0.0` once the existing release workflow publishes it. Before
   publication, test this checkout or a wheel built from the reviewed commit;
   an immutable full-commit Git dependency pin can identify that same source
   revision. The version change in this repository does not itself publish a
   package or create a release tag.

Verified source translation caches do not need to be deleted for this
migration: the projection happens when results are assembled. Matching criteria
and source-integrity validation keep their existing behavior.
