from tui_kit.app_header import AppHeader
from textual.message import Message
from textual.widgets import Static


class SettingsRequested(Message):
    """The account link in the header was clicked."""


class AccountLink(Static):
    """The email in use, or "Settings" until one is known; clicking it opens Settings like , does."""

    def show(self, account: str) -> None:
        self.update(account or "Settings")

    def on_click(self) -> None:
        self.post_message(SettingsRequested())


class YafHeader(AppHeader):
    """tui-kit's header, with the server when it is not production, the score and the account on the right.

    The app and the saying widget fill the labels through show_account and show_score.
    """

    def __init__(self) -> None:
        super().__init__(
            Static("", id="app-url"),
            Static("", id="header-score"),
            AccountLink("Settings", id="app-account", markup=False),
        )

    def show_account(self, email: str, server: str = "") -> None:
        """The email in use, and the server's name when it is worth calling out; "" hides either."""
        self.query_one(AccountLink).show(email)
        url = self.query_one("#app-url", Static)
        url.update(server)
        url.display = bool(server)

    def show_score(self, score: int | None) -> None:
        self.query_one("#header-score", Static).update(str(score) if score is not None else "")
