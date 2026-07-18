"""Bounded and failure-aware access to the GetBible Scripture repository."""

from collections import OrderedDict
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, Optional, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from getbible.errors import (
    DataValidationError,
    InvalidReferenceError,
    ScriptureNotFoundError,
    TranslationNotFoundError,
    UpstreamUnavailableError,
)
from getbible.getbible_reference import BookReference, GetBibleReference


_MISSING = object()


class _TtlLruCache:
    """Small thread-safe TTL/LRU cache with a hard entry limit."""

    def __init__(self, max_size: int, ttl_seconds: float) -> None:
        if max_size < 1 or ttl_seconds <= 0:
            raise ValueError("Cache size and TTL must be positive.")
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._values = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str) -> Any:
        now = time.monotonic()
        with self._lock:
            item = self._values.get(key, _MISSING)
            if item is _MISSING:
                return _MISSING
            created_at, value = item
            if now - created_at >= self._ttl_seconds:
                self._values.pop(key, None)
                return _MISSING
            self._values.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._values[key] = (time.monotonic(), value)
            self._values.move_to_end(key)
            while len(self._values) > self._max_size:
                self._values.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


class GetBible:
    WORD_OPTIONS = {"allwords", "anywords", "exactwords"}
    MATCH_OPTIONS = {"exactmatch", "partialmatch"}
    CASE_OPTIONS = {"caseinsensitive", "casesensitive"}
    TARGET_OPTIONS = {"allbooks", "oldtestament", "newtestament"} | set(
        map(str, range(1, 84))
    )

    _TRANSLATION_PATTERN = re.compile(r"[a-z0-9]{1,30}")

    def __init__(
        self,
        repo_path: str = "https://api.getbible.net",
        version: str = "v2",
        connect_timeout: float = 3.05,
        read_timeout: float = 10.0,
        retries: int = 2,
        cache_size: int = 512,
        cache_ttl_seconds: float = 3600.0,
        negative_cache_ttl_seconds: float = 300.0,
        max_references: int = 8,
        max_total_verses: int = 200,
        session: Optional[requests.Session] = None,
        reference_parser: Optional[GetBibleReference] = None,
    ) -> None:
        if not isinstance(repo_path, str) or not repo_path.strip():
            raise ValueError("repo_path must be a non-empty URL or filesystem path.")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("version must be non-empty.")
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("HTTP timeouts must be positive.")
        if retries < 0 or max_references < 1 or max_total_verses < 1:
            raise ValueError("Retry and request limits are invalid.")

        self.__repo_path = repo_path.rstrip("/")
        self.__repo_version = version.strip("/")
        self.__repo_path_url = self.__repo_path.startswith(("http://", "https://"))
        self.__timeout = (connect_timeout, read_timeout)  # type: Tuple[float, float]
        self.__max_references = max_references
        self.__max_total_verses = max_total_verses
        self.__get = reference_parser or GetBibleReference(max_verses=max_total_verses)
        self.__books_cache = _TtlLruCache(cache_size, cache_ttl_seconds)
        self.__negative_books_cache = _TtlLruCache(cache_size, negative_cache_ttl_seconds)
        self.__chapters_cache = _TtlLruCache(cache_size, cache_ttl_seconds)
        self.__owns_session = session is None
        self.__session = session or requests.Session()

        if self.__owns_session:
            retry = Retry(
                total=retries,
                connect=retries,
                read=retries,
                status=retries,
                backoff_factor=0.25,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                respect_retry_after_header=True,
                raise_on_status=False,
            )
            adapter = HTTPAdapter(
                max_retries=retry,
                pool_connections=min(cache_size, 32),
                pool_maxsize=min(cache_size, 32),
            )
            self.__session.mount("https://", adapter)
            self.__session.mount("http://", adapter)
        self.__session.headers.setdefault("User-Agent", "getbible-librarian/1.2")

    @property
    def available_translations(self) -> frozenset:
        """Translation codes known locally; reading this property performs no network I/O."""
        return self.__get.available_translations

    def select(
        self, reference: str, abbreviation: Optional[str] = "kjv"
    ) -> Dict[str, Union[Dict, str]]:
        """Select Scripture while enforcing reference and total-work budgets."""
        if not isinstance(reference, str):
            raise InvalidReferenceError("Reference must be text.")

        normalized_abbreviation = (abbreviation or "kjv").strip().casefold()
        references = [item.strip() for item in reference.split(";")]
        if not references or any(not item for item in references):
            raise InvalidReferenceError("Every reference must be non-empty.")
        if len(references) > self.__max_references:
            raise InvalidReferenceError(
                f"A request may contain at most {self.__max_references} references."
            )

        parsed_references = []
        total_verses = 0
        for raw_reference in references:
            parsed = self.__get.ref(raw_reference, normalized_abbreviation)
            total_verses += len(parsed.verses)
            if total_verses > self.__max_total_verses:
                raise InvalidReferenceError(
                    f"A request may select at most {self.__max_total_verses} verses."
                )
            parsed_references.append(parsed)

        self.__check_translation(normalized_abbreviation)
        result = {}  # type: Dict[str, Union[Dict, str]]
        for parsed in parsed_references:
            self.__set_verse(normalized_abbreviation, parsed, result)
        return result

    def scripture(self, reference: str, abbreviation: Optional[str] = "kjv") -> str:
        return json.dumps(self.select(reference, abbreviation), ensure_ascii=False)

    def valid_reference(self, reference: str, abbreviation: Optional[str] = "kjv") -> bool:
        return self.__get.valid(reference, abbreviation)

    def valid_translation(self, abbreviation: str) -> bool:
        """Validate only locally known codes, then confirm the configured repository has them."""
        if not isinstance(abbreviation, str):
            return False
        normalized = abbreviation.strip().casefold()
        if not self._TRANSLATION_PATTERN.fullmatch(normalized):
            return False
        if normalized not in self.available_translations:
            return False

        negative = self.__negative_books_cache.get(normalized)
        if negative is not _MISSING:
            return False
        cached = self.__books_cache.get(normalized)
        if cached is not _MISSING:
            return True

        path = self.__generate_path(normalized, "books.json")
        books = self.__fetch_data(path)
        if books is None:
            self.__negative_books_cache.set(normalized, True)
            return False
        self.__books_cache.set(normalized, books)
        return True

    def valid_limit(self, limit: str) -> bool:
        parts = limit.split("-")
        if len(parts) != 4:
            return False
        words, match, case, target = parts
        return (
            words in self.WORD_OPTIONS
            and match in self.MATCH_OPTIONS
            and case in self.CASE_OPTIONS
            and target in self.TARGET_OPTIONS
        )

    def close(self) -> None:
        if self.__owns_session:
            self.__session.close()

    def __enter__(self) -> "GetBible":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def __set_verse(
        self,
        abbreviation: str,
        book_ref: BookReference,
        result: Dict[str, Union[Dict, str]],
    ) -> None:
        cache_key = f"{abbreviation}_{book_ref.book}_{book_ref.chapter}"
        chapter_data = self.__chapters_cache.get(cache_key)
        if chapter_data is _MISSING:
            fetched = self.__retrieve_chapter_data(
                abbreviation, book_ref.book, book_ref.chapter
            )
            chapter_data = self.__normalize_chapter_data(fetched)
            self.__chapters_cache.set(cache_key, chapter_data)

        verse_map = chapter_data["verses"]
        for verse in book_ref.verses:
            verse_info = verse_map.get(str(verse))
            if not verse_info:
                raise ScriptureNotFoundError(
                    f"Verse {verse} not found in book {book_ref.book}, chapter {book_ref.chapter}."
                )

            existing = result.get(cache_key)
            if isinstance(existing, dict):
                existing_verses = {str(item.get("verse")) for item in existing.get("verses", [])}
                if str(verse) not in existing_verses:
                    existing["verses"].append(verse_info)
                if book_ref.reference not in existing.get("ref", []):
                    existing["ref"].append(book_ref.reference)
            else:
                selected = {key: value for key, value in chapter_data.items() if key != "verses"}
                selected["ref"] = [book_ref.reference]
                selected["verses"] = [verse_info]
                result[cache_key] = selected

    def __normalize_chapter_data(self, chapter_data: Any) -> Dict[str, Any]:
        if not isinstance(chapter_data, dict):
            raise DataValidationError("Chapter data must be a JSON object.")
        verses = chapter_data.get("verses")
        if not isinstance(verses, list):
            raise DataValidationError("Chapter data is missing its verse list.")

        verse_map = {}
        for verse in verses:
            if not isinstance(verse, dict) or "verse" not in verse:
                raise DataValidationError("Chapter data contains an invalid verse entry.")
            verse_number = verse["verse"]
            if not isinstance(verse_number, int) or verse_number < 1:
                raise DataValidationError("Chapter data contains an invalid verse number.")
            verse_map[str(verse_number)] = verse

        normalized = dict(chapter_data)
        normalized["verses"] = verse_map
        return normalized

    def __check_translation(self, abbreviation: str) -> None:
        if not self.valid_translation(abbreviation):
            raise TranslationNotFoundError(f"Translation ({abbreviation}) not found.")

    def __generate_path(self, abbreviation: str, file_name: str) -> str:
        if self.__repo_path_url:
            return f"{self.__repo_path}/{self.__repo_version}/{abbreviation}/{file_name}"
        return os.path.join(self.__repo_path, self.__repo_version, abbreviation, file_name)

    def __fetch_data(self, path: str) -> Any:
        if self.__repo_path_url:
            try:
                response = self.__session.get(path, timeout=self.__timeout)
            except requests.Timeout as error:
                raise UpstreamUnavailableError("The Scripture repository timed out.") from error
            except requests.RequestException as error:
                raise UpstreamUnavailableError("The Scripture repository is unavailable.") from error

            if response.status_code == 404:
                return None
            if response.status_code < 200 or response.status_code >= 300:
                raise UpstreamUnavailableError(
                    f"The Scripture repository returned HTTP {response.status_code}."
                )
            try:
                payload = response.json()
            except (ValueError, requests.RequestException) as error:
                raise DataValidationError("The Scripture repository returned invalid JSON.") from error
            if not isinstance(payload, (dict, list)):
                raise DataValidationError("The Scripture repository returned an invalid JSON value.")
            return payload

        file_path = Path(path)
        if not file_path.is_file():
            return None
        try:
            with file_path.open("r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
        except (OSError, json.JSONDecodeError) as error:
            raise DataValidationError(f"Unable to read Scripture data from {file_path}.") from error
        if not isinstance(payload, (dict, list)):
            raise DataValidationError(f"Scripture data in {file_path} has an invalid shape.")
        return payload

    def __retrieve_chapter_data(self, abbreviation: str, book: int, chapter: int) -> Dict:
        chapter_file = (
            f"{book}/{chapter}.json"
            if self.__repo_path_url
            else os.path.join(str(book), f"{chapter}.json")
        )
        chapter_data = self.__fetch_data(self.__generate_path(abbreviation, chapter_file))
        if chapter_data is None:
            raise ScriptureNotFoundError(
                f"Chapter:{chapter} in book:{book} for {abbreviation} not found."
            )
        if not isinstance(chapter_data, dict):
            raise DataValidationError("Chapter data must be a JSON object.")
        return chapter_data
