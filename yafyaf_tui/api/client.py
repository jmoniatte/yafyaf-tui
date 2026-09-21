"""Blocking HTTP client for the YafYaf REST API; call it from a worker thread in the TUI."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from http import HTTPStatus
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
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


class NotFoundError(ApiError):
    """The record does not exist, or was deleted."""


class ApiConnectionError(Exception):
    """The server could not be reached."""


@dataclass(frozen=True, slots=True)
class User:
    id: str
    email: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "User":
        return cls(id=str(data["id"]), email=data["email"])


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
    # The #words in the content, read out by the server
    tags: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Yaf":
        return cls(
            id=str(data["id"]),
            content=data.get("content") or "",
            date=date.fromisoformat(data["date"]),
            tags=tuple(data.get("tags") or ()),
        )

    @property
    def summary(self) -> str:
        """The first non-empty line, which is all a list row can show."""
        for line in self.content.splitlines():
            if line.strip():
                return line.strip()
        return ""


@dataclass(frozen=True, slots=True)
class Tag:
    name: str
    count: int


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
        # Every response carries a saying, and authenticated ones the user's score; on_response,
        # when set, runs on the calling thread after they are updated
        self.saying = ""
        self.score: int | None = None
        self.on_response: Callable[[], None] | None = None

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

    def list_tags(self) -> list[Tag]:
        """The user's tags with how many yafs carry each, by name; a search for "#name" filters on one."""
        data = self.request("GET", "/api/tags")
        return [Tag(name=str(tag["name"]), count=int(tag["count"])) for tag in data.get("tags") or ()]

    def get_yaf(self, yaf_id: str) -> Yaf:
        return Yaf.from_json(self.request("GET", f"/api/yafs/{yaf_id}")["yaf"])

    def create_yaf(self, content: str, day: date) -> Yaf:
        data = self.request("POST", "/api/yafs", {"yaf": _yaf_fields(content, day)})
        return Yaf.from_json(data["yaf"])

    def update_yaf(self, yaf_id: str, content: str, day: date) -> Yaf:
        data = self.request("PATCH", f"/api/yafs/{yaf_id}", {"yaf": _yaf_fields(content, day)})
        return Yaf.from_json(data["yaf"])

    def delete_yaf(self, yaf_id: str) -> None:
        self.request("DELETE", f"/api/yafs/{yaf_id}")

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
                self._note_response(response.headers)
                return _parse_json(response.read())
        except HTTPError as error:
            self._note_response(error.headers)
            raise _api_error(error) from None
        except (URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise ApiConnectionError(f"Cannot reach {self.base_url}: {reason}") from None

    def _note_response(self, headers: Mapping[str, str]) -> None:
        # The server percent-encodes the saying, since header values are ASCII
        self.saying = unquote(headers.get("x-yaf-says") or "")
        try:
            self.score = int(headers.get("x-yaf-score") or "")
        except ValueError:
            self.score = None
        if self.on_response is not None:
            self.on_response()


def _yaf_fields(content: str, day: date) -> dict[str, str]:
    return {"content": content, "date": day.isoformat()}


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
    if error.code == HTTPStatus.NOT_FOUND:
        return NotFoundError(error.code, message)
    return ApiError(error.code, message)
