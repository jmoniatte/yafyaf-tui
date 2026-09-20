from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static

from .. import REPOSITORY_URL, __version__
from .header_notification import HeaderNotification
from .web_link import WebLink


class SettingsRequested(Message):
    """The account link in the header was clicked."""


class AccountLink(Static):
    """The email in use, or "Settings" until one is known; clicking it opens Settings like ? does."""

    def show(self, account: str) -> None:
        self.update(account or "Settings")

    def on_click(self) -> None:
        self.post_message(SettingsRequested())


class AppHeader(Horizontal):
    """The title bar, the notification area, the server when it is not production, the account and the score."""

    def __init__(self, **kwargs) -> None:
        super().__init__(id="app-header", **kwargs)

    def compose(self) -> ComposeResult:
        with Vertical(id="app-title-group"):
            yield WebLink(REPOSITORY_URL, label="YafYaf", id="app-title")
            yield Static(__version__, id="app-subtitle")
        yield Static("", classes="header-notification-spacer")
        yield HeaderNotification()
        yield Static("", id="header-spacer")
        yield Static("", id="app-url")  # The app fills in the server, when it is not production
        yield Static("", id="echo-score")  # Filled by Echo
        yield AccountLink("Settings", id="app-account", markup=False)  # The app fills in the email in use
