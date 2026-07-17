"""Retrieve multiple references and print the established JSON contract."""

import json

from getbible import GetBible


def main() -> int:
    bible = GetBible()
    result = bible.select("Genesis 1:1-3;John 3:16", "kjv")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
