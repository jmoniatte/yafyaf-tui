import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

CONFIG_DIR = Path.home() / ".config" / "yafyaf-tui"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
TOKENS_DIR = CONFIG_DIR / "tokens"
DEFAULT_THEME = "onedark"
DEFAULT_URL = "https://yafyaf.com"
URL_ENV_VAR = "YAFYAF_URL"


@dataclass
class Config:
    """Optional, hand-edited settings; the server URL and token are not among them."""

    theme: str = DEFAULT_THEME
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

    config.theme = str(data.get("theme") or DEFAULT_THEME)
    return config


def resolve_url(flag: str | None = None, environ: Mapping[str, str] = os.environ) -> str:
    """Pick the server: the --url flag, then $YAFYAF_URL, then production."""
    url = flag or environ.get(URL_ENV_VAR) or DEFAULT_URL
    return url.strip().rstrip("/")


class TokenStore:
    """One API token per server, each in its own user-only file so config.yaml holds no secrets."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_url(cls, url: str, directory: Path = TOKENS_DIR) -> "TokenStore":
        parts = urlsplit(url)
        name = parts.hostname or "unknown"
        if parts.port:
            name = f"{name}_{parts.port}"
        return cls(directory / name)

    def load(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""

    def save(self, token: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token + "\n")
        os.chmod(self.path, 0o600)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
