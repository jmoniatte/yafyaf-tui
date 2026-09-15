from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from .. import REPOSITORY_URL, __version__
from ..config import DEFAULT_URL
from .header_notification import HeaderNotification
from .web_link import WebLink


class AppHeader(Horizontal):
    """The title bar every screen shares, plus whatever that screen puts on the right."""

    def __init__(self, url: str = DEFAULT_URL, *trailing: Widget, **kwargs) -> None:
        super().__init__(id="app-header", **kwargs)
        self._url = url
        self._trailing = trailing

    def compose(self) -> ComposeResult:
        with Vertical(id="app-title-group"):
            yield WebLink(REPOSITORY_URL, label="YafYaf", id="app-title")
            yield Static(f"v{__version__}", id="app-subtitle")
        yield Static("", classes="header-notification-spacer")
        yield HeaderNotification()
        yield Static("", id="header-spacer")
        # Only a non-production server is worth calling out
        if self._url != DEFAULT_URL:
            yield Static(self._url, id="app-url")
        yield from self._trailing
