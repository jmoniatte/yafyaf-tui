import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_DIR = Path.home() / ".config" / "yafyaf-tui"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
TOKEN_FILE = CONFIG_DIR / "token"
DEFAULT_THEME = "onedark"


@dataclass
class Config:
    """Settings the user edits by hand; secrets live in TokenStore."""

    theme: str = DEFAULT_THEME
    url: str = ""
    # Why the config file could not be used; the UI shows these
    warnings: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return bool(self.url)


def load_config(path: Path = CONFIG_FILE) -> Config:
    """Read the config file; return defaults plus warnings when it is missing or invalid."""
    config = Config()
    if not path.exists():
        config.warnings.append(f"Config file not found: {path}")
        return config

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        config.warnings.append(f"Config file is not valid YAML: {error}")
        return config
    if not isinstance(data, dict):
        config.warnings.append("Config file must contain a mapping of settings")
        return config

    config.theme = str(data.get("theme") or DEFAULT_THEME)
    config.url = str(data.get("url") or "").rstrip("/")
    if not config.url:
        config.warnings.append("Missing setting: url")
    return config


class TokenStore:
    """The API token, kept in its own user-only file so config.yaml holds no secrets."""

    def __init__(self, path: Path = TOKEN_FILE) -> None:
        self.path = path

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
