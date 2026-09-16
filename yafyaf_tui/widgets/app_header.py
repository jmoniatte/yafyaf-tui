from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from .. import REPOSITORY_URL, __version__
from ..config import DEFAULT_URL
from .header_notification import HeaderNotification
from .web_link import WebLink


class AppHeader(Horizontal):
    """The title bar, the notification area, the server when it is not production, and Settings."""

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
        settings = Button("Settings", id="btn-settings")
        # Clicking must not pull focus off the list, which the screen would then hand back to the button
        settings.can_focus = False
        yield settings
