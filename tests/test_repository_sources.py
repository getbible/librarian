import json
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from getbible import GetBible, SearchBible

FIXTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "repository"


class _SilentRepositoryHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class TestRepositorySources(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        handler = partial(_SilentRepositoryHandler, directory=str(FIXTURE_REPOSITORY))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        host, port = cls.server.server_address
        cls.repository_url = f"http://{host}:{port}/"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        cache_root = Path(self.temporary.name)
        self.local = GetBible(
            repo_path=FIXTURE_REPOSITORY,
            cache_dir=cache_root / "local",
        )
        self.remote = GetBible(
            repo_path=self.repository_url,
            cache_dir=cache_root / "remote",
            require_checksums=False,
        )

    def tearDown(self) -> None:
        self.local.close()
        self.remote.close()
        self.temporary.cleanup()

    def test_local_path_and_remote_url_return_identical_scripture(self):
        local = self.local.scripture("1 1:1-3", "test")
        remote = self.remote.scripture("1 1:1-3", "test")
        self.assertEqual(json.loads(local), json.loads(remote))

    def test_local_path_and_remote_url_return_identical_search_results(self):
        search = SearchBible(words="all", limit=2)
        local = self.local.search("faith hope", "test", search)
        remote = self.remote.search("faith hope", "test", search)

        remote["query"]["cache"]["checked_at"] = local["query"]["cache"][
            "checked_at"
        ]
        self.assertEqual(local, remote)

    def test_close_releases_remote_http_sessions(self):
        self.assertTrue(self.remote.valid_translation("test"))
        sessions = tuple(self.remote._repository._sessions)
        self.assertEqual(len(sessions), 1)
        with patch.object(sessions[0], "close", wraps=sessions[0].close) as close:
            self.remote.close()
        close.assert_called_once_with()
        self.assertEqual(self.remote._repository._sessions, set())


if __name__ == "__main__":
    unittest.main()
