"""Blocking HTTP client for the YafYaf REST API; call it from a worker thread in the TUI."""

import json
from dataclasses import dataclass
from datetime import date, datetime
from http import HTTPStatus
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .. import __version__

DEFAULT_TIMEOUT = 10.0
DEFAULT_SORT = "date desc"


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


@dataclass(frozen=True, slots=True)
class Yaf:
    id: str
    content: str
    date: date
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Yaf":
        return cls(
            id=str(data["id"]),
            content=data.get("content") or "",
            date=date.fromisoformat(data["date"]),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
        )

    @property
    def summary(self) -> str:
        """The first non-empty line, which is all a list row can show."""
        for line in self.content.splitlines():
            if line.strip():
                return line.strip()
        return ""


@dataclass(frozen=True, slots=True)
class YafPage:
    """One page of a list or search, plus how to ask for the next one."""

    yafs: tuple[Yaf, ...]
    records_count: int
    next_page: dict[str, Any] | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "YafPage":
        meta = data.get("meta") or {}
        next_page = meta.get("next_page") or None
        return cls(
            yafs=tuple(Yaf.from_json(item) for item in data.get("yafs") or ()),
            records_count=int(meta.get("records_count") or 0),
            next_page=next_page.get("params") if next_page else None,
        )


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

    def list_yafs(self, q: str = "", page: int = 1, sort: str = DEFAULT_SORT) -> YafPage:
        """List the user's yafs, full-text filtered by q when given, newest date first."""
        params: dict[str, Any] = {"page": page, "sort": sort}
        if q:
            params["q"] = q
        return YafPage.from_json(self.request("GET", "/api/yafs", params=params))

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
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

        url = self.base_url + path
        if params:
            url += "?" + urlencode(params)
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return _parse_json(response.read())
        except HTTPError as error:
            raise _api_error(error) from None
        except (URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise ApiConnectionError(f"Cannot reach {self.base_url}: {reason}") from None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
