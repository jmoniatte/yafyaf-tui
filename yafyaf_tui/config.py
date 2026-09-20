import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .theme import TERMINAL_THEME, default_theme, is_known_theme, list_themes

CONFIG_DIR = Path.home() / ".config" / "yafyaf-tui"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
TOKENS_FILE = CONFIG_DIR / "tokens.yaml"
# Where versions before 0.5 kept one token file per account, under a directory per server
LEGACY_TOKENS_DIR = CONFIG_DIR / "tokens"
DEFAULT_URL = "https://yafyaf.com"
URL_ENV_VAR = "YAFYAF_URL"
_THEME_LINE = re.compile(r"^theme:.*$", re.MULTILINE)


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def server_name(url: str) -> str:
    """How a server is shown: its host, with the port when there is one."""
    return urlsplit(url).netloc or url


@dataclass
class Config:
    """Optional, hand-edited settings; the tokens are not among them."""

    # "terminal" reads the terminal's own colours; otherwise any scheme in
    # styles/themes/ (see theme.list_themes()). Falls back to theme.default_theme().
    theme: str = TERMINAL_THEME
    # The servers the login screen offers; production alone unless the file lists more
    servers: list[str] = field(default_factory=lambda: [DEFAULT_URL])
    # Why the config file was ignored; the UI shows these
    warnings: list[str] = field(default_factory=list)

    def servers_with(self, url: str) -> list[str]:
        """The servers to offer when url is in use: the configured ones, with url first if it is not among them."""
        return self.servers if url in self.servers else [url, *self.servers]


def load_config(path: Path = CONFIG_FILE) -> Config:
    """Read the config file if there is one; a missing file just means defaults."""
    config = Config()
    if not path.exists():
        return config

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        config.warnings.append(f"Config file is not valid YAML: {error}")
        return config
    if not isinstance(data, Mapping):
        config.warnings.append("Config file must contain a mapping of settings")
        return config

    theme = data.get("theme")
    if isinstance(theme, str) and theme.strip():
        if is_known_theme(theme.strip()):
            config.theme = theme.strip()
        else:
            config.theme = default_theme()
            # Too many themes to list; a near-miss is the useful hint.
            near = get_close_matches(theme.strip(), list_themes(), n=3)
            hint = f" Did you mean: {', '.join(near)}?" if near else ""
            config.warnings.append(
                f"theme: '{theme.strip()}' is not installed, using '{config.theme}'.{hint}"
            )

    servers = data.get("servers")
    if servers is not None:
        if not isinstance(servers, list) or not all(isinstance(url, str) for url in servers):
            config.warnings.append("servers: must be a list of URLs")
        else:
            valid = []
            for url in servers:
                url = normalize_url(url)
                if urlsplit(url).scheme in ("http", "https") and urlsplit(url).netloc:
                    if url not in valid:
                        valid.append(url)
                else:
                    config.warnings.append(f"servers: '{url}' is not a URL, ignoring it")
            if valid:
                config.servers = valid
    return config


def save_theme(theme: str, path: Path = CONFIG_FILE) -> None:
    """Persist the theme, leaving the rest of a hand-written config untouched."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"theme: {theme}"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    updated, replaced = _THEME_LINE.subn(line, text, count=1)
    path.write_text(updated if replaced else f"{line}\n{text}", encoding="utf-8")


def resolve_url(flag: str | None = None, environ: Mapping[str, str] = os.environ, default: str = DEFAULT_URL) -> str:
    """Pick the server: the --url flag, then $YAFYAF_URL, then the default (production unless told otherwise)."""
    return normalize_url(flag or environ.get(URL_ENV_VAR) or default)


def url_was_given(flag: str | None = None, environ: Mapping[str, str] = os.environ) -> bool:
    return bool(flag or environ.get(URL_ENV_VAR))


@dataclass(frozen=True, slots=True)
class Account:
    """One login: an email on one server."""

    url: str
    email: str

    @property
    def host(self) -> str:
        return server_name(self.url)

    @property
    def label(self) -> str:
        """The email alone on production, with the server otherwise."""
        return self.email if self.url == DEFAULT_URL else f"{self.email} ({self.host})"


class TokenStore:
    """The API tokens, one per account (server and email), in a single user-only YAML file.

    The file holds the accounts in the order they were added and which one is current.
    Tokens for several servers live side by side, which is what lets the app move between
    them without restarting.
    """

    def __init__(self, path: Path = TOKENS_FILE) -> None:
        self.path = path

    @classmethod
    def default(cls) -> "TokenStore":
        """The user's store, taking over the per-file tokens of older versions on first use."""
        store = cls()
        store.import_legacy(LEGACY_TOKENS_DIR)
        return store

    # -- reading

    def accounts(self) -> list[Account]:
        return [Account(entry["url"], entry["email"]) for entry in self._read()["accounts"]]

    def accounts_on(self, url: str) -> list[Account]:
        return [account for account in self.accounts() if account.url == url]

    def current(self) -> Account | None:
        data = self._read()
        current = data["current"]
        if not current:
            return None
        account = Account(current["url"], current["email"])
        return account if account in self.accounts() else None

    def token(self, account: Account | None) -> str:
        if account is None:
            return ""
        for entry in self._read()["accounts"]:
            if (entry["url"], entry["email"]) == (account.url, account.email):
                return entry["token"]
        return ""

    def resolve(self, url: str, email: str = "") -> Account | None:
        """The account to use on a server: the one with that email, else the current one if it is there, else the first."""
        on_server = self.accounts_on(url)
        if email:
            return next((account for account in on_server if account.email == email), None)
        current = self.current()
        if current is not None and current.url == url:
            return current
        return on_server[0] if on_server else None

    def find(self, email: str) -> Account | None:
        """The first account with that email on any server."""
        return next((account for account in self.accounts() if account.email == email), None)

    # -- writing

    def save(self, account: Account, token: str) -> None:
        """Store an account's token and make it current."""
        data = self._read()
        entries = [e for e in data["accounts"] if (e["url"], e["email"]) != (account.url, account.email)]
        entries.append({"url": account.url, "email": account.email, "token": token})
        data["accounts"] = entries
        data["current"] = {"url": account.url, "email": account.email}
        self._write(data)

    def select(self, account: Account) -> None:
        data = self._read()
        data["current"] = {"url": account.url, "email": account.email}
        self._write(data)

    def clear(self, account: Account | None) -> None:
        """Forget an account's token; if it was current, another on the same server, else any other, takes over."""
        if account is None:
            return
        data = self._read()
        data["accounts"] = [
            e for e in data["accounts"] if (e["url"], e["email"]) != (account.url, account.email)
        ]
        current = data["current"]
        if current and (current["url"], current["email"]) == (account.url, account.email):
            remaining = data["accounts"]
            same_server = [e for e in remaining if e["url"] == account.url]
            next_entry = (same_server or remaining or [None])[0]
            data["current"] = {"url": next_entry["url"], "email": next_entry["email"]} if next_entry else None
        self._write(data)

    def import_legacy(self, directory: Path) -> None:
        """Bring the tokens of the per-file layout into this store, then remove that layout."""
        if not directory.is_dir():
            return
        current = None
        for server_dir in sorted(directory.iterdir()):
            if not server_dir.is_dir():
                continue  # A single token without an email cannot be filed; that login is asked again
            host, _, port = server_dir.name.partition("_")
            local = host in ("localhost", "127.0.0.1") or bool(port)
            url = f"{'http' if local else 'https'}://{host}{':' + port if port else ''}"
            selected = self._read_text(server_dir / "current")
            for token_file in sorted(server_dir.iterdir()):
                if token_file.name == "current" or not token_file.is_file():
                    continue
                account = Account(url, token_file.name)
                self.save(account, self._read_text(token_file))
                if account.email == selected:
                    current = account
        if current is not None:
            self.select(current)
        shutil.rmtree(directory)

    # -- file

    def _read(self) -> dict:
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except (FileNotFoundError, yaml.YAMLError):
            data = {}
        accounts = [
            e for e in (data.get("accounts") or [])
            if isinstance(e, dict) and all(isinstance(e.get(k), str) for k in ("url", "email", "token"))
        ]
        current = data.get("current")
        if not (isinstance(current, dict) and isinstance(current.get("url"), str) and isinstance(current.get("email"), str)):
            current = None
        return {"current": current, "accounts": accounts}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        # Written next to the file and renamed over it, so a crash mid-write cannot lose every token
        temp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temp, 0o600)
        os.replace(temp, self.path)

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
