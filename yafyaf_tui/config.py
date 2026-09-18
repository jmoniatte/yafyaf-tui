import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .theme import TERMINAL_THEME, default_theme, is_known_theme, list_themes

CONFIG_DIR = Path.home() / ".config" / "yafyaf-tui"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
TOKENS_DIR = CONFIG_DIR / "tokens"
DEFAULT_URL = "https://yafyaf.com"
URL_ENV_VAR = "YAFYAF_URL"
_THEME_LINE = re.compile(r"^theme:.*$", re.MULTILINE)


@dataclass
class Config:
    """Optional, hand-edited settings; the server URL and token are not among them."""

    # "terminal" reads the terminal's own colours; otherwise any scheme in
    # styles/themes/ (see theme.list_themes()). Falls back to theme.default_theme().
    theme: str = TERMINAL_THEME
    # Why the config file was ignored; the UI shows these
    warnings: list[str] = field(default_factory=list)


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
    return config


def save_theme(theme: str, path: Path = CONFIG_FILE) -> None:
    """Persist the theme, leaving the rest of a hand-written config untouched."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"theme: {theme}"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    updated, replaced = _THEME_LINE.subn(line, text, count=1)
    path.write_text(updated if replaced else f"{line}\n{text}", encoding="utf-8")


def resolve_url(flag: str | None = None, environ: Mapping[str, str] = os.environ) -> str:
    """Pick the server: the --url flag, then $YAFYAF_URL, then production."""
    url = flag or environ.get(URL_ENV_VAR) or DEFAULT_URL
    return url.strip().rstrip("/")


class TokenStore:
    """The API tokens for one server: a user-only file per account, plus which account is current.

    `path` is a directory named after the server, holding one file per email and a `current`
    file naming the account in use. Older versions kept a single file at `path` with one
    token and no email; it is read as the current token until `save` files it under its email.
    """

    _CURRENT = "current"

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_url(cls, url: str, directory: Path = TOKENS_DIR) -> "TokenStore":
        parts = urlsplit(url)
        name = parts.hostname or "unknown"
        if parts.port:
            name = f"{name}_{parts.port}"
        return cls(directory / name)

    def accounts(self) -> list[str]:
        """The emails with a stored token, in file order."""
        if not self.path.is_dir():
            return []
        return sorted(entry.name for entry in self.path.iterdir() if entry.is_file() and entry.name != self._CURRENT)

    def current(self) -> str:
        """The account in use, or "" when none is stored (or only a legacy token without an email)."""
        account = self._read(self.path / self._CURRENT)
        return account if account in self.accounts() else ""

    def load(self, account: str = "") -> str:
        """The token for an account, by default the current one."""
        if self.path.is_file():
            return self._read(self.path)
        account = account or self.current()
        return self._read(self.path / account) if account else ""

    def save(self, token: str, account: str) -> None:
        """Store an account's token and make it current."""
        if self.path.is_file():
            self.path.unlink()
        self.path.mkdir(parents=True, exist_ok=True)
        self._write(self.path / account, token)
        self.select(account)

    def select(self, account: str) -> None:
        self._write(self.path / self._CURRENT, account)

    def clear(self, account: str = "") -> None:
        """Forget an account's token, by default the current one; the next stored account becomes current."""
        if self.path.is_file():
            self.path.unlink()
            return
        account = account or self.current()
        if account:
            (self.path / account).unlink(missing_ok=True)
        remaining = self.accounts()
        if not remaining:
            (self.path / self._CURRENT).unlink(missing_ok=True)
        elif not self.current():
            self.select(remaining[0])

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            return ""

    @staticmethod
    def _write(path: Path, text: str) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        os.chmod(path, 0o600)
