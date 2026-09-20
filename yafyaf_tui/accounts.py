"""The signed-in accounts: one API token per server and email, all in one user-only file."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import CONFIG_DIR, DEFAULT_URL, server_name

TOKENS_FILE = CONFIG_DIR / "tokens.yaml"
# Where versions before 0.5 kept one token file per account, under a directory per server
LEGACY_TOKENS_DIR = CONFIG_DIR / "tokens"


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

    def starting_account(self, url: str, email: str = "", url_given: bool = False) -> Account | None:
        """Which account a run starts on, given the server it was pointed at and the --as email, if any.

        The email is looked for on that server, and on every server when the server was not
        chosen explicitly, so `--as` alone finds the account wherever it is stored.
        """
        account = self.resolve(url, email)
        if account is None and email and not url_given:
            account = self.find(email)
        return account

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
