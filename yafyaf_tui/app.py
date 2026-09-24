from pathlib import Path

import ouikit
from ouikit.base_app import HELP_BINDING, THEME_BINDING, BaseApp
from ouikit.shortcuts import GENERAL
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding

from . import REPOSITORY_URL, __version__
from .account_flow import AccountFlow
from .accounts import Account, TokenStore
from .api import User, YafyafClient
from .config import CONFIG_FILE, DEFAULT_URL, Config, load_config
from .edit_flow import EditFlow
from .screens import SettingsScreen
from .widgets import (
    EditRequested,
    ListColors,
    MainArea,
    NewYafRequested,
    RetryRequested,
    SettingsRequested,
    TagSelected,
    ViewClosed,
    YafDetail,
    YafHeader,
    YafOpened,
    YafsTable,
    YafsView,
)

STYLES_DIR = Path(__file__).parent / "styles"
# One stylesheet per component, in cascade order: later files may rely on rules in earlier ones
STYLE_FILES = (
    *ouikit.STYLE_FILES,
    *(STYLES_DIR / f"{name}.tcss" for name in ("header", "main_area", "yaf_detail", "saying", "settings", "login")),
)


def load_stylesheet() -> str:
    return "\n".join(path.read_text() for path in STYLE_FILES)


class YafyafApp(AccountFlow, EditFlow, BaseApp):
    """Terminal client for the YafYaf notes API.

    The account and editing flows live in their mixins; this class holds the state they share,
    the layout and the message handlers that hand off to them; BaseApp brings the theme, the
    header messages and Help.
    """

    TITLE = "YafYaf"
    VERSION = __version__
    REPOSITORY_URL = REPOSITORY_URL
    HELP_BINDINGS = (YafsView.BINDINGS, YafsTable.BINDINGS, YafDetail.BINDINGS)

    BINDINGS = [
        HELP_BINDING,
        Binding("comma", "settings", "Settings", key_display=",", group=GENERAL),
        THEME_BINDING,
        Binding("s", "next_account", "Switch account", group=GENERAL),
        Binding("q", "quit", "Quit", group=GENERAL),
    ]

    def __init__(
        self,
        url: str = DEFAULT_URL,
        config: Config | None = None,
        token_store: TokenStore | None = None,
        account: Account | None = None,
        login_email: str = "",
    ) -> None:
        self.config = config if config is not None else load_config()
        self.token_store = token_store if token_store is not None else TokenStore.default()
        # The account whose token is in use, or None until the first login; it names the server too
        self.account = account if (account or login_email) else self.token_store.resolve(url)
        self.url = self.account.url if self.account else url
        # Offered by the login screen; the server in use is always among them
        self.servers = self.config.servers_with(self.url)
        self._login_email = login_email
        self.client = YafyafClient(self.url, self.token_store.token(self.account))
        self.user: User | None = None
        self.CSS = load_stylesheet()
        super().__init__(self.config.theme, CONFIG_FILE)

    def compose(self) -> ComposeResult:
        yield YafHeader()
        yield MainArea(self.client, self._list_colors())

    @property
    def main(self) -> MainArea:
        return self.query_one(MainArea)

    def _list_colors(self) -> ListColors:
        return ListColors(
            date=self.palette["comment"],
            link=self.palette["blue"],
            heading=self.palette["yellow"],
            tag=self.palette["purple"],
        )

    def on_mount(self) -> None:
        for warning in self.config.warnings:
            self.notify(warning, severity="warning", timeout=10)
        self._show_account()
        if self.client.token:
            self._check_token()
        else:
            self._ask_login(email=self._login_email)

    # -- theme

    def apply_theme(self, theme_name: str) -> None:
        super().apply_theme(theme_name)
        # refresh_css only re-applies TCSS; the list and the view bake some colors into Rich text
        self.main.set_colors(self._list_colors())

    # -- messages from the widgets

    @on(SettingsRequested)
    def action_settings(self) -> None:
        self.push_screen(SettingsScreen())

    @on(RetryRequested)
    def _retry(self) -> None:
        self._check_token()

    @on(ViewClosed)
    def _close_view(self) -> None:
        if self.main.viewing is not None:
            self.main.show_list()

    @on(TagSelected)
    def _tag_selected(self, event: TagSelected) -> None:
        """A tag clicked anywhere filters the list; from the view that means going back to it."""
        if self.main.viewing is not None:
            self.main.show_list()
        self.query_one(YafsView).add_tag(event.name)

    @on(YafOpened)
    def _open_yaf(self, event: YafOpened) -> None:
        self._fetch_and_show(event.yaf)

    @on(EditRequested)
    def _edit_requested(self, event: EditRequested) -> None:
        self._fetch_and_edit(event.yaf)

    @on(NewYafRequested)
    def _new_yaf(self) -> None:
        self._edit_yaf(None)
