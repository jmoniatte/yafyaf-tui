from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Button, Static


class RetryRequested(Message):
    """The user asked to try the server again."""


class OfflineNotice(Vertical):
    """Stands in for the yaf list while the server cannot be used.

    Taking focus from the list is what removes its keys (new yaf, search, refresh) while
    the server is down; the app's own keys (settings, theme, quit) stay.
    """

    BINDINGS = [Binding("r", "retry", "Retry", show=False)]
    can_focus = True

    def __init__(self, server: str, **kwargs) -> None:
        super().__init__(id="offline", **kwargs)
        self._server = server

    def compose(self) -> ComposeResult:
        yield Static(f"{self._server} is not available", id="offline-title", markup=False)
        yield Static("", id="offline-detail", markup=False)
        yield Button("Retry (r)", id="btn-retry")

    def show(self, detail: str) -> None:
        self.query_one("#offline-detail", Static).update(detail)
        self.display = True
        self.focus()

    def hide(self) -> None:
        self.display = False

    @on(Button.Pressed, "#btn-retry")
    def action_retry(self) -> None:
        self.post_message(RetryRequested())
