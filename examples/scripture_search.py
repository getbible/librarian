"""Search scripture and print the unified search response.

The first search shows the whole of what a caller has to do: hand over a query
string. The second narrows a search with filters, which is what the criteria are
for — they never describe how a writing system should be read.
"""

import json

from getbible import GetBible, SearchBible


def main() -> int:
    with GetBible() as bible:
        # A bare query works in every translation the API publishes, whether or
        # not its script separates words with spaces.
        for query, translation in (
            ("faith hope", "kjv"),
            ("神爱世人", "cus"),
            ("사랑", "korean"),
            ("בראשית", "modernhebrew"),
        ):
            response = bible.search(query, translation)
            print(
                f"{translation:14} {query:12} "
                f"{response['query']['total']:>5} verses "
                f"({response['query']['analysis']['script']})"
            )

        narrowed = bible.search(
            "faith hope",
            "kjv",
            SearchBible(scope="new_testament", exclude=("charity",), limit=20),
        )
    print(json.dumps(narrowed, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
