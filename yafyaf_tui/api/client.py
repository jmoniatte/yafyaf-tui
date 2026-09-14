"""Blocking HTTP client for the YafYaf REST API; call it from a worker thread in the TUI."""

import json
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .. import __version__

DEFAULT_TIMEOUT = 10.0


class ApiError(Exception):
    """The server answered with an error status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class AuthenticationError(ApiError):
    """The token is missing, unknown, or revoked."""


class ApiConnectionError(Exception):
    """The server could not be reached."""


@dataclass(frozen=True, slots=True)
class User:
    id: str
    email: str
    locale: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "User":
        return cls(id=str(data["id"]), email=data["email"], locale=data.get("locale"))


@dataclass(frozen=True, slots=True)
class Session:
    """A freshly issued token and the user it belongs to."""

    user: User
    token: str


class YafyafClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def login(self, email: str, password: str) -> Session:
        """Exchange credentials for a token and remember it on this client."""
        data = self.request(
            "POST",
            "/api/auth_tokens",
            {"user": {"email": email, "password": password}},
            authenticated=False,
        )
        session = Session(user=User.from_json(data["user"]), token=data["auth_token"]["token"])
        self.token = session.token
        return session

    def logout(self) -> None:
        """Revoke the current token server-side and forget it."""
        if not self.token:
            return
        self.request("DELETE", f"/api/auth_tokens/{self.token}")
        self.token = ""

    def me(self) -> User:
        return User.from_json(self.request("GET", "/api/users/me")["user"])

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"yafyaf-tui/{__version__}",
        }
        if authenticated:
            if not self.token:
                raise AuthenticationError(HTTPStatus.UNAUTHORIZED, "Not logged in")
            headers["Authorization"] = f"Bearer {self.token}"
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(self.base_url + path, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return _parse_json(response.read())
        except HTTPError as error:
            raise _api_error(error) from None
        except (URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise ApiConnectionError(f"Cannot reach {self.base_url}: {reason}") from None


def _parse_json(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {"data": data}


def _api_error(error: HTTPError) -> ApiError:
    """Turn the API's {"error": ...} and {"errors": {...}} bodies into one message."""
    message = error.reason or "Request failed"
    try:
        data = _parse_json(error.read())
    except ValueError:
        data = {}
    if isinstance(data.get("error"), str):
        message = data["error"]
    elif isinstance(data.get("errors"), dict):
        message = "; ".join(f"{field} {problem}" for field, problem in data["errors"].items())
    if error.code == HTTPStatus.UNAUTHORIZED:
        return AuthenticationError(error.code, message)
    return ApiError(error.code, message)
