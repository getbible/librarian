"""Reliable access to remote and local GetBible API-compatible repositories."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import (
    RepositoryError,
    RepositoryResourceNotFound,
    RepositoryResponseError,
)


class RepositoryClient:
    """Read bytes, text, and JSON from an API v2-compatible repository.

    A thread-local :class:`requests.Session` keeps connection pooling efficient
    without sharing mutable ``Session`` state between application threads.
    """

    def __init__(
        self,
        repo_path: str | os.PathLike[str] = "https://api.getbible.net",
        version: str = "v2",
        timeout: tuple[float, float] = (3.05, 60.0),
        retries: int = 3,
        backoff_factor: float = 0.25,
    ) -> None:
        source = os.fspath(repo_path)
        if source.startswith(("http://", "https://")):
            self.repo_path = source.rstrip("/")
        else:
            self.repo_path = os.path.normpath(os.path.expanduser(source))
        self.version = version.strip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff_factor = backoff_factor
        self.is_url = self.repo_path.startswith(("http://", "https://"))
        self._thread_local = threading.local()
        self._sessions: set[requests.Session] = set()
        self._sessions_guard = threading.Lock()

    def fetch_bytes(self, relative_path: str) -> bytes:
        """Return a repository resource as bytes."""
        if self.is_url:
            url = self.location(relative_path)
            try:
                response = self._session().get(url, timeout=self.timeout)
            except requests.RequestException as error:
                raise RepositoryError(f"Unable to fetch {url}: {error}") from error

            if response.status_code == 404:
                raise RepositoryResourceNotFound(f"Repository resource not found: {url}")
            try:
                response.raise_for_status()
            except requests.RequestException as error:
                raise RepositoryError(f"Unable to fetch {url}: {error}") from error
            return response.content

        path = Path(self.location(relative_path))
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise RepositoryResourceNotFound(
                f"Repository resource not found: {path}"
            ) from error
        except OSError as error:
            raise RepositoryError(f"Unable to read {path}: {error}") from error

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
        """Return the URL or local path for a relative API resource."""
        clean_relative = relative_path.lstrip("/")
        if self.is_url:
            return f"{self.repo_path}/{self.version}/{clean_relative}"
        return os.path.join(self.repo_path, self.version, clean_relative)

    def close(self) -> None:
        """Close every HTTP session created by this client.

        Call this only during worker or application shutdown, after request
        threads have stopped using the client.
        """
        with self._sessions_guard:
            sessions = tuple(self._sessions)
            self._sessions.clear()
        for session in sessions:
            session.close()
        for name in ("session", "process_id"):
            if hasattr(self._thread_local, name):
                delattr(self._thread_local, name)

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
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        session = requests.Session()
        session.headers.update({"User-Agent": "getbible-librarian"})
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        self._thread_local.session = session
        self._thread_local.process_id = process_id
        with self._sessions_guard:
            self._sessions.add(session)
        return session
