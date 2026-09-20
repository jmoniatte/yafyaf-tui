from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.notifications import Notification, SeverityLevel

from .account_flow import AccountFlow
from .accounts import Account, TokenStore
from .api import User, YafyafClient
from .config import DEFAULT_URL, Config, load_config, save_theme
from .edit_flow import EditFlow
from .screens import SettingsScreen, ThemePicker
from .shortcuts import GENERAL
from .theme import effective_theme, load_palette
from .widgets import (
    AppHeader,
    EditRequested,
    HeaderNotification,
    ListColors,
    MainArea,
    NewYafRequested,
    RetryRequested,
    SettingsRequested,
    ViewClosed,
    YafOpened,
    YafsView,
)

STYLES_DIR = Path(__file__).parent / "styles"
# One stylesheet per component, in cascade order: later files may rely on rules in earlier ones
STYLE_FILES = ("base", "header", "main_area", "yaf_detail", "saying", "settings", "modal_forms", "dialogs", "login", "theme_picker")


def load_stylesheet() -> str:
    return "\n".join((STYLES_DIR / f"{name}.tcss").read_text() for name in STYLE_FILES)


class YafyafApp(AccountFlow, EditFlow, App):
    """Terminal client for the YafYaf notes API.

    The account and editing flows live in their mixins; this class holds the state they share,
    the layout, the theme, the notifications and the message handlers that hand off to them.
    """

    TITLE = "YafYaf"

    BINDINGS = [
        Binding("question_mark", "settings", "Settings", key_display="?", group=GENERAL),
        Binding("t", "show_themes", "Change theme", group=GENERAL),
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
        # The palette is served from get_css_variables rather than baked into
        # CSS, so apply_theme can swap it without restarting.
        self._palette = load_palette(self.config.theme)
        self.CSS = load_stylesheet()
        super().__init__()

    def compose(self) -> ComposeResult:
        yield AppHeader()
        yield MainArea(self.client, self._list_colors())

    @property
    def main(self) -> MainArea:
        return self.query_one(MainArea)

    def _list_colors(self) -> ListColors:
        return ListColors(date=self._palette["comment"], link=self._palette["blue"], heading=self._palette["yellow"])

    def get_css_variables(self) -> dict[str, str]:
        """Serve the base16 palette to the stylesheet alongside Textual's own."""
        return {**super().get_css_variables(), **self._palette}

    def on_mount(self) -> None:
        for warning in self.config.warnings:
            self.notify(warning, severity="warning", timeout=10)
        self._show_account()
        if self.client.token:
            self._check_token()
        else:
            self._ask_login(email=self._login_email)

    # -- theme

    def action_show_themes(self) -> None:
        """Browse themes, applying each one as the cursor moves."""
        self.push_screen(ThemePicker(effective_theme(self.config.theme)), callback=self._theme_chosen)

    def _theme_chosen(self, theme_name: str | None) -> None:
        if theme_name is not None:
            self.set_theme(theme_name)

    def set_theme(self, theme_name: str) -> None:
        """Apply a theme and remember it for next launch."""
        if effective_theme(theme_name) == effective_theme(self.config.theme):
            return
        self.apply_theme(theme_name)
        self.config.theme = theme_name
        save_theme(theme_name)
        self.notify(f"Theme set to {theme_name}")

    def apply_theme(self, theme_name: str) -> None:
        """Swap the palette and repaint in place."""
        self._palette = load_palette(theme_name)
        self.refresh_css()
        # refresh_css only re-applies TCSS; the list bakes its colors into Rich text
        self.query_one(YafsView).set_colors(self._list_colors())

    # -- notifications

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "information",
        timeout: float | None = None,
        markup: bool = False,
    ) -> None:
        """Show notifications in the header instead of as toasts.

        Messages carry server errors and file paths, which may contain brackets, so markup is never on.
        """
        notification = Notification(message, title, severity, self.NOTIFICATION_TIMEOUT if timeout is None else timeout)
        self.call_later(self._show_notification, notification)

    def _show_notification(self, notification: Notification) -> None:
        for screen in reversed(self.screen_stack):
            notifications = list(screen.query(HeaderNotification))
            if notifications:
                notifications[0].show_notification(notification)
                return
        super().notify(
            notification.message,
            title=notification.title,
            severity=notification.severity,
            timeout=max(notification.time_left, 0),
            markup=False,
        )

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

    @on(YafOpened)
    def _open_yaf(self, event: YafOpened) -> None:
        self._fetch_and_show(event.yaf)

    @on(EditRequested)
    def _edit_requested(self, event: EditRequested) -> None:
        self._fetch_and_edit(event.yaf)

    @on(NewYafRequested)
    def _new_yaf(self) -> None:
        self._edit_yaf(None)
