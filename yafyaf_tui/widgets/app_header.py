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
    """The title bar, the notification area, the server when it is not production, the account and the score.

    The app and the saying widget fill the labels through show_account and show_score.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(id="app-header", **kwargs)

    def compose(self) -> ComposeResult:
        with Vertical(id="app-title-group"):
            yield WebLink(REPOSITORY_URL, label="YafYaf", id="app-title")
            yield Static(__version__, id="app-subtitle")
        yield Static("", classes="header-notification-spacer")
        yield HeaderNotification()
        yield Static("", id="header-spacer")
        yield Static("", id="app-url")
        yield Static("", id="echo-score")
        yield AccountLink("Settings", id="app-account", markup=False)

    def show_account(self, email: str, server: str = "") -> None:
        """The email in use, and the server's name when it is worth calling out; "" hides either."""
        self.query_one(AccountLink).show(email)
        url = self.query_one("#app-url", Static)
        url.update(server)
        url.display = bool(server)

    def show_score(self, score: int | None) -> None:
        self.query_one("#echo-score", Static).update(str(score) if score is not None else "")
