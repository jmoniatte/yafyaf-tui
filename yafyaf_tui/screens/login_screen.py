import asyncio
from dataclasses import dataclass

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from ..api import ApiConnectionError, ApiError, Session, YafyafClient
from ..config import server_name


@dataclass(frozen=True, slots=True)
class Login:
    """A successful login: the server it was made on and what it returned."""

    url: str
    session: Session


class LoginScreen(ModalScreen[Login | None]):
    """Ask for email and password and exchange them for an API token.

    With several servers configured, a dropdown picks which one to log in to.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        servers: list[str],
        url: str,
        message: str = "",
        email: str = "",
        cancel_label: str = "Quit",
    ) -> None:
        super().__init__()
        self._servers = servers
        self._url = url if url in servers else servers[0]
        self._message = message
        self._email = email
        self._cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Vertical(id="login-dialog"):
            yield Static("Log in", id="dialog-title")
            if len(self._servers) > 1:
                with Horizontal(classes="form-row"):
                    yield Static("Server", classes="field-label")
                    yield Select(
                        options=[(server_name(url), url) for url in self._servers],
                        value=self._url,
                        id="login-server",
                        allow_blank=False,
                    )
            else:
                yield Static(self._url, id="login-url")
            with Horizontal(classes="form-row"):
                yield Static("Email", classes="field-label")
                yield Input(self._email, placeholder="you@example.com", id="email")
            with Horizontal(classes="form-row"):
                yield Static("Password", classes="field-label")
                yield Input(password=True, id="password")
            yield Static(self._message, id="login-error")
            with Horizontal(id="dialog-buttons"):
                yield Button(self._cancel_label, id="cancel-btn")
                yield Button("Log in", id="login-btn")

    def on_mount(self) -> None:
        self.query_one("#password" if self._email else "#email", Input).focus()

    @property
    def url(self) -> str:
        """The server the login goes to."""
        if len(self._servers) > 1:
            return str(self.query_one("#login-server", Select).value)
        return self._url

    @on(Input.Submitted)
    def _submit_from_input(self, event: Input.Submitted) -> None:
        if event.input.id == "email":
            self.query_one("#password", Input).focus()
        else:
            self._submit()

    @on(Button.Pressed, "#login-btn")
    def _submit_from_button(self) -> None:
        self._submit()

    @on(Button.Pressed, "#cancel-btn")
    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        email = self.query_one("#email", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not email or not password:
            self._show_error("Email and password are required")
            return
        self._set_busy(True)
        self._login(self.url, email, password)

    @work(exclusive=True)
    async def _login(self, url: str, email: str, password: str) -> None:
        client = YafyafClient(url)
        try:
            session = await asyncio.to_thread(client.login, email, password)
        except (ApiError, ApiConnectionError) as error:
            self._set_busy(False)
            self._show_error(str(error))
            return
        self.dismiss(Login(url, session))

    def _set_busy(self, busy: bool) -> None:
        self.query_one("#login-btn", Button).disabled = busy
        self.query_one("#login-error", Static).update("Logging in..." if busy else "")

    def _show_error(self, message: str) -> None:
        self.query_one("#login-error", Static).update(message)
