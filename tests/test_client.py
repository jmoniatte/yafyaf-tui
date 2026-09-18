import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

from yafyaf_tui import __version__
from yafyaf_tui.api import ApiConnectionError, ApiError, AuthenticationError, NotFoundError, YafyafClient

USER = {"id": "abc", "email": "me@example.com", "locale": "en"}
YAFS = [
    {
        "id": "y1",
        "content": "First yaf\nmore",
        "date": "2026-09-13",
        "created_at": "2026-09-13T10:00:00.000Z",
        "updated_at": "2026-09-13T11:00:00.000Z",
    },
    {"id": "y2", "content": "Second yaf", "date": "2026-09-12", "created_at": None, "updated_at": None},
]


class FakeYafyaf(BaseHTTPRequestHandler):
    """Just enough of the YafYaf API to exercise the client's request and error handling."""

    requests: list[dict] = []

    def _record(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        entry = {
            "method": self.command,
            "path": self.path,
            "headers": dict(self.headers),
            "body": json.loads(raw) if raw else None,
        }
        FakeYafyaf.requests.append(entry)
        return entry

    def _reply(self, status: int, body: dict | None = None) -> None:
        self.send_response(status)
        payload = json.dumps(body).encode() if body is not None else b""
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        # Like the real API: a saying on every response, the score only when the token was accepted
        self.send_header("x-yaf-says", "There is always time.")
        if status != 401 and self._authorized(FakeYafyaf.requests[-1]):
            self.send_header("x-yaf-score", "94")
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self, entry: dict) -> bool:
        return entry["headers"].get("Authorization") == "Bearer good-token"

    def do_POST(self) -> None:
        entry = self._record()
        if self.path == "/api/yafs":
            if not self._authorized(entry):
                return self._reply(401, {"error": "Authentication is required and has failed"})
            return self._reply(200, {"yaf": {**YAFS[1], "id": "y3", **entry["body"]["yaf"]}})
        if self.path != "/api/auth_tokens":
            return self._reply(404, {"error": "Record not found"})
        user = (entry["body"] or {}).get("user", {})
        if user.get("email") == USER["email"] and user.get("password") == "secret":
            return self._reply(200, {"user": USER, "auth_token": {"token": "good-token"}})
        self._reply(400, {"error": "Invalid email or password."})

    def do_GET(self) -> None:
        entry = self._record()
        if not self._authorized(entry):
            return self._reply(401, {"error": "Authentication is required and has failed"})
        if self.path == "/api/users/me":
            return self._reply(200, {"user": USER})
        parts = urlsplit(self.path)
        if parts.path == "/api/yafs":
            query = parse_qs(parts.query)
            page = int(query.get("page", ["1"])[0])
            next_page = None
            if page == 1:
                next_page = {"params": {"page": 2, "sort": "date desc"}, "url": "http://x/api/yafs?page=2"}
            return self._reply(200, {"yafs": YAFS, "meta": {"records_count": 4, "next_page": next_page}})
        if self.path == "/api/yafs/y1":
            return self._reply(200, {"yaf": YAFS[0]})
        if self.path == "/api/invalid":
            return self._reply(422, {"errors": {"title": "can't be blank", "body": "is too long"}})
        self._reply(404, {"error": "Record not found"})

    def do_PATCH(self) -> None:
        entry = self._record()
        if not self._authorized(entry):
            return self._reply(401, {"error": "Authentication is required and has failed"})
        if self.path != "/api/yafs/y1":
            return self._reply(404, {"error": "Record not found"})
        self._reply(200, {"yaf": {**YAFS[0], **entry["body"]["yaf"]}})

    def do_DELETE(self) -> None:
        entry = self._record()
        if not self._authorized(entry):
            return self._reply(401, {"error": "Authentication is required and has failed"})
        if self.path == "/api/yafs/gone":
            return self._reply(404, {"error": "Record not found"})
        self._reply(204)

    def log_message(self, *args) -> None:
        pass


class ClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeYafyaf)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        FakeYafyaf.requests = []

    def test_login_sends_json_credentials_and_keeps_the_token(self) -> None:
        client = YafyafClient(self.base_url)
        session = client.login("me@example.com", "secret")

        self.assertEqual(session.token, "good-token")
        self.assertEqual(session.user.email, "me@example.com")
        self.assertEqual(client.token, "good-token")
        self.assertEqual(client.base_url, self.base_url.rstrip("/"))

        sent = FakeYafyaf.requests[0]
        self.assertEqual((sent["method"], sent["path"]), ("POST", "/api/auth_tokens"))
        self.assertEqual(sent["body"], {"user": {"email": "me@example.com", "password": "secret"}})
        self.assertEqual(sent["headers"]["Accept"], "application/json")
        self.assertEqual(sent["headers"]["Content-Type"], "application/json")
        self.assertEqual(sent["headers"]["User-Agent"], f"yafyaf-tui/{__version__}")
        self.assertNotIn("Authorization", sent["headers"])

    def test_login_failure_surfaces_the_server_message(self) -> None:
        client = YafyafClient(self.base_url)
        with self.assertRaises(ApiError) as raised:
            client.login("me@example.com", "wrong")
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(str(raised.exception), "Invalid email or password.")
        self.assertEqual(client.token, "")

    def test_me_uses_the_bearer_token(self) -> None:
        client = YafyafClient(self.base_url, token="good-token")
        user = client.me()
        self.assertEqual(user.id, "abc")
        self.assertEqual(FakeYafyaf.requests[0]["headers"]["Authorization"], "Bearer good-token")

    def test_saying_and_score_are_read_off_the_response_headers(self) -> None:
        seen = []
        client = YafyafClient(self.base_url, token="good-token", on_response=lambda: seen.append(client.score))
        client.me()
        self.assertEqual((client.saying, client.score), ("There is always time.", 94))

        # The saying still arrives on a rejected token, the score does not
        client.token = "stale"
        with self.assertRaises(AuthenticationError):
            client.me()
        self.assertEqual((client.saying, client.score), ("There is always time.", None))
        self.assertEqual(seen, [94, None])

    def test_rejected_or_missing_token_raises_authentication_error(self) -> None:
        with self.assertRaises(AuthenticationError) as raised:
            YafyafClient(self.base_url, token="stale").me()
        self.assertEqual(raised.exception.status, 401)

        with self.assertRaises(AuthenticationError):
            YafyafClient(self.base_url).me()
        self.assertEqual(len(FakeYafyaf.requests), 1)

    def test_validation_errors_are_joined_into_one_message(self) -> None:
        client = YafyafClient(self.base_url, token="good-token")
        with self.assertRaises(ApiError) as raised:
            client.request("GET", "/api/invalid")
        self.assertEqual(raised.exception.status, 422)
        self.assertEqual(str(raised.exception), "title can't be blank; body is too long")

    def test_logout_revokes_and_forgets_the_token(self) -> None:
        client = YafyafClient(self.base_url, token="good-token")
        client.logout()
        self.assertEqual(client.token, "")
        sent = FakeYafyaf.requests[0]
        self.assertEqual((sent["method"], sent["path"]), ("DELETE", "/api/auth_tokens/good-token"))

        client.logout()
        self.assertEqual(len(FakeYafyaf.requests), 1)

    def test_unreachable_server_raises_connection_error(self) -> None:
        client = YafyafClient("http://127.0.0.1:1", timeout=1)
        with self.assertRaises(ApiConnectionError) as raised:
            client.login("me@example.com", "secret")
        self.assertIn("Cannot reach http://127.0.0.1:1", str(raised.exception))

    def test_list_yafs_sends_search_params_and_parses_the_page(self) -> None:
        client = YafyafClient(self.base_url, token="good-token")
        page = client.list_yafs("hello world", page=1)

        sent = FakeYafyaf.requests[0]
        parts = urlsplit(sent["path"])
        self.assertEqual(parts.path, "/api/yafs")
        self.assertEqual(parse_qs(parts.query), {"page": ["1"], "sort": ["date desc"], "q": ["hello world"]})

        self.assertEqual(page.records_count, 4)
        self.assertEqual(page.next_page, {"page": 2, "sort": "date desc"})
        self.assertEqual([yaf.id for yaf in page.yafs], ["y1", "y2"])
        first, second = page.yafs
        self.assertEqual(first.date, date(2026, 9, 13))
        self.assertEqual(first.summary, "First yaf")
        self.assertEqual(first.updated_at, datetime(2026, 9, 13, 11, tzinfo=timezone.utc))
        self.assertIsNone(second.created_at)

        last = client.list_yafs(page=2)
        self.assertNotIn("q=", FakeYafyaf.requests[1]["path"])
        self.assertIsNone(last.next_page)

    def test_get_yaf_returns_the_yaf_or_raises_not_found(self) -> None:
        client = YafyafClient(self.base_url, token="good-token")
        yaf = client.get_yaf("y1")
        self.assertEqual((yaf.id, yaf.content), ("y1", "First yaf\nmore"))
        self.assertEqual(FakeYafyaf.requests[0]["path"], "/api/yafs/y1")

        with self.assertRaises(NotFoundError) as raised:
            client.get_yaf("gone")
        self.assertEqual((raised.exception.status, str(raised.exception)), (404, "Record not found"))

    def test_delete_yaf_sends_delete_and_raises_not_found_when_gone(self) -> None:
        client = YafyafClient(self.base_url, token="good-token")
        self.assertIsNone(client.delete_yaf("y1"))
        sent = FakeYafyaf.requests[0]
        self.assertEqual((sent["method"], sent["path"]), ("DELETE", "/api/yafs/y1"))

        with self.assertRaises(NotFoundError):
            client.delete_yaf("gone")

    def test_create_yaf_sends_content_and_date_and_returns_the_new_yaf(self) -> None:
        client = YafyafClient(self.base_url, token="good-token")
        created = client.create_yaf("New yaf", date(2026, 9, 14))

        sent = FakeYafyaf.requests[0]
        self.assertEqual((sent["method"], sent["path"]), ("POST", "/api/yafs"))
        self.assertEqual(sent["body"], {"yaf": {"content": "New yaf", "date": "2026-09-14"}})
        self.assertEqual((created.id, created.content, created.date), ("y3", "New yaf", date(2026, 9, 14)))

    def test_update_yaf_sends_the_content_and_returns_the_saved_yaf(self) -> None:
        client = YafyafClient(self.base_url, token="good-token")
        saved = client.update_yaf("y1", "Edited yaf", date(2026, 9, 10))

        sent = FakeYafyaf.requests[0]
        self.assertEqual((sent["method"], sent["path"]), ("PATCH", "/api/yafs/y1"))
        self.assertEqual(sent["body"], {"yaf": {"content": "Edited yaf", "date": "2026-09-10"}})
        self.assertEqual((saved.id, saved.content, saved.date), ("y1", "Edited yaf", date(2026, 9, 10)))

        with self.assertRaises(NotFoundError) as raised:
            client.update_yaf("missing", "x", date(2026, 9, 10))
        self.assertEqual(raised.exception.status, 404)
