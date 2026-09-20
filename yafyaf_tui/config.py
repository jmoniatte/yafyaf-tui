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
