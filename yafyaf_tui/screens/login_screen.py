import asyncio

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from ..api import ApiConnectionError, ApiError, Session, YafyafClient


class LoginScreen(ModalScreen[Session | None]):
    """Ask for email and password and exchange them for an API token."""

    BINDINGS = [
        ("escape", "cancel", "Quit"),
    ]

    def __init__(self, client: YafyafClient, message: str = "") -> None:
        super().__init__()
        self._client = client
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="login-dialog"):
            yield Static("Log in", id="dialog-title")
            yield Static(self._client.base_url, id="login-url")
            with Horizontal(classes="form-row"):
                yield Static("Email", classes="field-label")
                yield Input(placeholder="you@example.com", id="email")
            with Horizontal(classes="form-row"):
                yield Static("Password", classes="field-label")
                yield Input(password=True, id="password")
            yield Static(self._message, id="login-error")
            with Horizontal(id="dialog-buttons"):
                yield Button("Quit", id="cancel-btn")
                yield Button("Log in", id="login-btn")

    def on_mount(self) -> None:
        self.query_one("#email", Input).focus()

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
        self._login(email, password)

    @work(exclusive=True)
    async def _login(self, email: str, password: str) -> None:
        try:
            session = await asyncio.to_thread(self._client.login, email, password)
        except (ApiError, ApiConnectionError) as error:
            self._set_busy(False)
            self._show_error(str(error))
            return
        self.dismiss(session)

    def _set_busy(self, busy: bool) -> None:
        self.query_one("#login-btn", Button).disabled = busy
        self.query_one("#login-error", Static).update("Logging in..." if busy else "")

    def _show_error(self, message: str) -> None:
        self.query_one("#login-error", Static).update(message)
