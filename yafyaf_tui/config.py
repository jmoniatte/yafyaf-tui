from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_DIR = Path.home() / ".config" / "yafyaf-tui"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
DEFAULT_THEME = "onedark"


@dataclass
class Config:
    """Application configuration with sensible defaults."""

    theme: str = DEFAULT_THEME
    url: str = ""
    token: str = ""
    # Why the config file could not be used; the UI shows these
    warnings: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return bool(self.url and self.token)


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
    config.token = str(data.get("token") or "")
    if not config.url:
        config.warnings.append("Missing setting: url")
    if not config.token:
        config.warnings.append("Missing setting: token")
    return config
