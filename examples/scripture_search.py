"""Search KJV scripture and print the unified search response."""

import json

from getbible import GetBible, SearchBible


def main() -> int:
    with GetBible() as bible:
        criteria = SearchBible(
            words="all",
            match="whole_word",
            case_sensitive=False,
            scope="new_testament",
            limit=20,
        )
        response = bible.search("faith hope", "kjv", criteria)
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
