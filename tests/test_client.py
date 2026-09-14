import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from yafyaf_tui import __version__
from yafyaf_tui.api import ApiConnectionError, ApiError, AuthenticationError, YafyafClient

USER = {"id": "abc", "email": "me@example.com", "locale": "en"}


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
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self, entry: dict) -> bool:
        return entry["headers"].get("Authorization") == "Bearer good-token"

    def do_POST(self) -> None:
        entry = self._record()
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
        if self.path == "/api/invalid":
            return self._reply(422, {"errors": {"title": "can't be blank", "body": "is too long"}})
        self._reply(404, {"error": "Record not found"})

    def do_DELETE(self) -> None:
        entry = self._record()
        if not self._authorized(entry):
            return self._reply(401, {"error": "Authentication is required and has failed"})
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
