import asyncio
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from .api import ApiConnectionError, AuthenticationError, Session, User, YafyafClient
from .config import DEFAULT_URL, Config, TokenStore, load_config
from .screens import HelpScreen, LoginScreen, YafDetailScreen
from .shortcuts import GENERAL
from .widgets import AppHeader, YafOpened, YafsView

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

    def __init__(
        self,
        url: str = DEFAULT_URL,
        config: Config | None = None,
        token_store: TokenStore | None = None,
    ) -> None:
        self.url = url
        self.config = config if config is not None else load_config()
        self.token_store = token_store if token_store is not None else TokenStore.for_url(url)
        self.client = YafyafClient(url, self.token_store.load())
        self.user: User | None = None
        self.CSS = build_css(self.config.theme)
        super().__init__()

    def compose(self) -> ComposeResult:
        yield AppHeader(self.url)
        yield YafsView(self.client)
        yield Static("", id="status-line")

    def on_mount(self) -> None:
        for warning in self.config.warnings:
            self.notify(warning, title="Config", severity="warning", timeout=10)
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
        self._signed_in_as(self.user)

    def _ask_login(self, message: str = "") -> None:
        self.push_screen(LoginScreen(self.client, message), self._signed_in)

    def _signed_in(self, session: Session | None) -> None:
        if session is None:
            self.exit()
            return
        self.user = session.user
        self.client.token = session.token
        self.token_store.save(session.token)
        self._signed_in_as(session.user)

    def _signed_in_as(self, user: User) -> None:
        self._set_status(f"Signed in as {user.email}")
        self.query_one(YafsView).load()

    def _set_status(self, text: str) -> None:
        self.query_one("#status-line", Static).update(text)

    @on(YafOpened)
    def _open_yaf(self, event: YafOpened) -> None:
        self.push_screen(YafDetailScreen(event.yaf))

    def action_help(self) -> None:
        self.push_screen(HelpScreen())
