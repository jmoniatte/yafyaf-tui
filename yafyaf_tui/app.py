import asyncio
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static

from .api import ApiConnectionError, AuthenticationError, Session, User, YafyafClient
from .config import CONFIG_FILE, Config, TokenStore, load_config
from .screens import HelpScreen, LoginScreen
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

    def __init__(self, config: Config | None = None, token_store: TokenStore | None = None) -> None:
        self.config = config if config is not None else load_config()
        self.token_store = token_store if token_store is not None else TokenStore()
        self.client = YafyafClient(self.config.url, self.token_store.load())
        self.user: User | None = None
        self.CSS = build_css(self.config.theme)
        super().__init__()

    def compose(self) -> ComposeResult:
        yield AppHeader()
        if not self.config.is_complete:
            yield from self._compose_no_config()
            return
        with Vertical(id="main"):
            yield Static("", id="main-placeholder")

    def _compose_no_config(self) -> ComposeResult:
        with Vertical(id="no-config-dialog"):
            yield Static("Configuration needed", id="dialog-title")
            yield Static(f"Create {CONFIG_FILE} with the url of your YafYaf.", id="no-config-message")
            yield Static("See config.yaml.example in the repository.", id="no-config-help")
            for warning in self.config.warnings:
                yield Static(warning, classes="no-config-warning")

    def on_mount(self) -> None:
        if not self.config.is_complete:
            return
        if self.client.token:
            self._check_token()
        else:
            self._ask_login()

    @work(exclusive=True)
    async def _check_token(self) -> None:
        """Confirm the stored token still works before showing anything that needs it."""
        try:
            self.user = await asyncio.to_thread(self.client.me)
        except AuthenticationError:
            self.token_store.clear()
            self.client.token = ""
            self._ask_login("Your saved token was rejected; please log in again.")
            return
        except ApiConnectionError as error:
            self._set_status(str(error))
            return
        self._set_status(f"Signed in as {self.user.email}")

    def _ask_login(self, message: str = "") -> None:
        self.push_screen(LoginScreen(self.client, message), self._signed_in)

    def _signed_in(self, session: Session | None) -> None:
        if session is None:
            self.exit()
            return
        self.user = session.user
        self.client.token = session.token
        self.token_store.save(session.token)
        self._set_status(f"Signed in as {self.user.email}")

    def _set_status(self, text: str) -> None:
        self.query_one("#main-placeholder", Static).update(text)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())
