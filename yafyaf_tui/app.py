from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static

from .config import CONFIG_FILE, Config, load_config
from .screens import HelpScreen
from .shortcuts import GENERAL
from .widgets import AppHeader

STYLES_DIR = Path(__file__).parent / "styles"


def build_css(theme: str) -> str:
    """Concatenate theme variables with base rules so the variables are in scope."""
    theme_path = STYLES_DIR / "themes" / f"{theme}.tcss"
    if not theme_path.exists():
        theme_path = STYLES_DIR / "themes" / "onedark.tcss"
    base_path = STYLES_DIR / "base.tcss"
    return theme_path.read_text() + "\n" + base_path.read_text()


class YafyafApp(App):
    """Terminal client for the YafYaf notes API."""

    TITLE = "YafYaf"

    BINDINGS = [
        Binding("question_mark", "help", "Help", key_display="?", group=GENERAL),
        Binding("q", "quit", "Quit", group=GENERAL),
    ]

    def __init__(self, config: Config | None = None) -> None:
        self.config = config if config is not None else load_config()
        self.CSS = build_css(self.config.theme)
        super().__init__()

    def compose(self) -> ComposeResult:
        yield AppHeader()
        if not self.config.is_complete:
            yield from self._compose_no_config()
            return
        with Vertical(id="main"):
            yield Static(f"Connected to {self.config.url}", id="main-placeholder")

    def _compose_no_config(self) -> ComposeResult:
        with Vertical(id="no-config-dialog"):
            yield Static("Configuration needed", id="dialog-title")
            yield Static(f"Create {CONFIG_FILE} with a url and a token.", id="no-config-message")
            yield Static("See config.yaml.example in the repository.", id="no-config-help")
            for warning in self.config.warnings:
                yield Static(warning, classes="no-config-warning")

    def action_help(self) -> None:
        self.push_screen(HelpScreen())
