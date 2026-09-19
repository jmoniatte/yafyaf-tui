from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static

from .. import REPOSITORY_URL, __version__
from ..config import DEFAULT_URL
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

    def __init__(self, url: str = DEFAULT_URL, **kwargs) -> None:
        super().__init__(id="app-header", **kwargs)
        self._url = url

    def compose(self) -> ComposeResult:
        with Vertical(id="app-title-group"):
            yield WebLink(REPOSITORY_URL, label="YafYaf", id="app-title")
            yield Static(__version__, id="app-subtitle")
        yield Static("", classes="header-notification-spacer")
        yield HeaderNotification()
        yield Static("", id="header-spacer")
        # Only a non-production server is worth calling out
        if self._url != DEFAULT_URL:
            yield Static(self._url, id="app-url")
        yield AccountLink("Settings", id="app-account", markup=False)  # The app fills in the email in use
        yield Static("", id="echo-score")  # Filled by Echo
