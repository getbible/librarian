"""Reliable, bounded access to GetBible API-compatible repositories."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path, PurePosixPath
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import (
    RepositoryError,
    RepositoryResourceNotFound,
    RepositoryResponseError,
    RepositoryResponseTooLarge,
    RepositoryTimeoutError,
)


class RepositoryClient:
    """Read bytes, text, and JSON from a repository with finite resource use.

    A thread-local :class:`requests.Session` keeps connection pooling efficient
    without sharing mutable ``Session`` state between application threads.
    Remote and local responses are size-bounded before their content is returned.
    """

    DEFAULT_MAX_RESPONSE_BYTES = 128 * 1024 * 1024
    _SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")

    def __init__(
        self,
        repo_path: str | os.PathLike[str] = "https://api.getbible.net",
        version: str = "v2",
        timeout: tuple[float, float] = (3.05, 30.0),
        retries: int = 3,
        backoff_factor: float = 0.25,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        try:
            source = os.fspath(repo_path)
        except TypeError as error:
            raise TypeError("repo_path must be a string or path-like value.") from error
        if not source.strip():
            raise ValueError("repo_path cannot be empty.")

        self.timeout = self._validated_timeout(timeout)
        self.retries = self._bounded_integer("retries", retries, minimum=0, maximum=10)
        self.backoff_factor = self._bounded_float(
            "backoff_factor", backoff_factor, minimum=0.0, maximum=60.0
        )
        self.max_response_bytes = self._bounded_integer(
            "max_response_bytes", max_response_bytes, minimum=1, maximum=1024**3
        )

        clean_version = version.strip("/") if isinstance(version, str) else ""
        if not clean_version or self._SAFE_SEGMENT.fullmatch(clean_version) is None:
            raise ValueError("version must contain only letters, numbers, '.', '_', or '-'.")
        self.version = clean_version

        if source.startswith(("http://", "https://")):
            self.repo_path = source.rstrip("/")
        else:
            self.repo_path = os.path.normpath(os.path.expanduser(source))
        self.is_url = self.repo_path.startswith(("http://", "https://"))
        self._thread_local = threading.local()
        self._sessions: set[requests.Session] = set()
        self._sessions_guard = threading.Lock()

    def fetch_bytes(self, relative_path: str) -> bytes:
        """Return a repository resource as bytes within the configured size cap."""
        clean_relative = self._validated_relative_path(relative_path)
        if self.is_url:
            return self._fetch_remote(clean_relative)
        return self._fetch_local(clean_relative)

    def fetch_text(self, relative_path: str) -> str:
        """Return a UTF-8 repository resource as text."""
        try:
            return self.fetch_bytes(relative_path).decode("utf-8")
        except UnicodeDecodeError as error:
            raise RepositoryResponseError(
                f"Repository resource is not valid UTF-8: {self.location(relative_path)}"
            ) from error

    def fetch_json(self, relative_path: str) -> dict[str, Any]:
        """Return a repository resource decoded as a JSON object."""
        raw = self.fetch_bytes(relative_path)
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RepositoryResponseError(
                f"Repository resource is not valid JSON: {self.location(relative_path)}"
            ) from error
        if not isinstance(value, dict):
            raise RepositoryResponseError(
                f"Repository JSON must contain an object: {self.location(relative_path)}"
            )
        return value

    def location(self, relative_path: str) -> str:
        """Return the URL or local path for a validated relative API resource."""
        clean_relative = self._validated_relative_path(relative_path)
        if self.is_url:
            return f"{self.repo_path}/{self.version}/{clean_relative}"
        root = (Path(self.repo_path) / self.version).resolve()
        candidate = (root / clean_relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise RepositoryError("Repository resource escaped the configured root.")
        return str(candidate)

    def close(self) -> None:
        """Close every HTTP session created by this client."""
        with self._sessions_guard:
            sessions = tuple(self._sessions)
            self._sessions.clear()
        for session in sessions:
            session.close()
        for name in ("session", "process_id"):
            if hasattr(self._thread_local, name):
                delattr(self._thread_local, name)

    def _fetch_remote(self, relative_path: str) -> bytes:
        url = self.location(relative_path)
        response: requests.Response | None = None
        try:
            response = self._session().get(url, timeout=self.timeout, stream=True)
            if response.status_code == 404:
                raise RepositoryResourceNotFound(f"Repository resource not found: {url}")
            response.raise_for_status()
            declared_size = response.headers.get("Content-Length")
            if declared_size is not None:
                try:
                    content_length = int(declared_size)
                except ValueError:
                    content_length = -1
                if content_length > self.max_response_bytes:
                    raise RepositoryResponseTooLarge(
                        f"Repository response exceeds {self.max_response_bytes} bytes: {url}"
                    )

            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > self.max_response_bytes:
                    raise RepositoryResponseTooLarge(
                        f"Repository response exceeds {self.max_response_bytes} bytes: {url}"
                    )
                chunks.append(chunk)
            return b"".join(chunks)
        except requests.Timeout as error:
            raise RepositoryTimeoutError(f"Repository request timed out: {url}") from error
        except RepositoryError:
            raise
        except requests.RequestException as error:
            raise RepositoryError(f"Unable to fetch {url}: {error}") from error
        finally:
            if response is not None:
                response.close()

    def _fetch_local(self, relative_path: str) -> bytes:
        path = Path(self.location(relative_path))
        try:
            size = path.stat().st_size
            if size > self.max_response_bytes:
                raise RepositoryResponseTooLarge(
                    f"Repository response exceeds {self.max_response_bytes} bytes: {path}"
                )
            return path.read_bytes()
        except RepositoryError:
            raise
        except FileNotFoundError as error:
            raise RepositoryResourceNotFound(
                f"Repository resource not found: {path}"
            ) from error
        except OSError as error:
            raise RepositoryError(f"Unable to read {path}: {error}") from error

    def _session(self) -> requests.Session:
        process_id = os.getpid()
        session = getattr(self._thread_local, "session", None)
        session_process_id = getattr(self._thread_local, "process_id", None)
        if session is not None and session_process_id == process_id:
            return session
        if session is not None:
            with self._sessions_guard:
                self._sessions.discard(session)
            session.close()

        retry = Retry(
            total=self.retries,
            connect=self.retries,
            read=self.retries,
            status=self.retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "getbible-librarian/1.2",
                "Accept": "application/json, text/plain;q=0.9, */*;q=0.1",
            }
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        self._thread_local.session = session
        self._thread_local.process_id = process_id
        with self._sessions_guard:
            self._sessions.add(session)
        return session

    @classmethod
    def _validated_relative_path(cls, relative_path: str) -> str:
        if not isinstance(relative_path, str):
            raise TypeError("relative_path must be a string.")
        candidate = relative_path.strip().replace("\\", "/")
        path = PurePosixPath(candidate)
        if (
            not candidate
            or candidate in {".", ".."}
            or candidate.startswith("/")
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(cls._SAFE_SEGMENT.fullmatch(part) is None for part in path.parts)
        ):
            raise ValueError("relative_path must be a safe repository-relative path.")
        return path.as_posix()

    @staticmethod
    def _validated_timeout(value: tuple[float, float]) -> tuple[float, float]:
        if not isinstance(value, tuple) or len(value) != 2:
            raise TypeError("timeout must be a (connect, read) tuple.")
        connect = RepositoryClient._bounded_float(
            "connect timeout", value[0], minimum=0.001, maximum=300.0
        )
        read = RepositoryClient._bounded_float(
            "read timeout", value[1], minimum=0.001, maximum=300.0
        )
        return connect, read

    @staticmethod
    def _bounded_integer(name: str, value: int, *, minimum: int, maximum: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an integer.")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")
        return value

    @staticmethod
    def _bounded_float(
        name: str,
        value: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"{name} must be numeric.")
        numeric = float(value)
        if not minimum <= numeric <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")
        return numeric
