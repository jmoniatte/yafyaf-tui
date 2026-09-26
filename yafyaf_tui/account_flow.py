"""How the app signs in, checks, switches and signs out of accounts; mixed into YafyafApp.

Message handlers stay on the app class, since Textual only registers them there; this holds the
work they delegate to.
"""

import asyncio

from tui_kit.dialog import ConfirmDialog
from textual import work

from .accounts import Account, TokenStore
from .api import ApiConnectionError, ApiError, AuthenticationError, User, YafyafClient
from .config import DEFAULT_URL, Config, server_name
from .screens import Login, LoginScreen
from .widgets import MainArea, YafHeader, YafsView


class AccountFlow:
    # Set by YafyafApp, which this mixes into
    config: Config
    token_store: TokenStore
    client: YafyafClient
    account: Account | None
    url: str
    servers: list[str]
    user: User | None
    main: MainArea

    @work(exclusive=True)
    async def _check_token(self) -> None:
        """Confirm the stored token still works before showing anything that needs it."""
        try:
            self.user = await asyncio.to_thread(self.client.me)
        except AuthenticationError:
            self.token_store.clear(self.account)
            self.client.token = ""
            self._use_next_account("Your saved token was rejected; please log in again.")
            return
        except ApiConnectionError as error:
            self._go_offline(str(error))
            return
        except ApiError as error:
            # A proxy answering for a server that is down, or a deploy in progress
            self._go_offline(f"The server answered {error.status}: {error}")
            return
        self.token_store.select(self.account)
        self._signed_in_as()

    def _ask_login(self, message: str = "", email: str = "", cancel_label: str = "Quit") -> None:
        screen = LoginScreen(self.servers, self.url, message, email=email, cancel_label=cancel_label)
        self.push_screen(screen, self._signed_in)

    def _signed_in(self, login: Login | None) -> None:
        if login is None:
            # Cancelling an added account leaves the current one; with nothing to fall back to, quit
            if not self.client.token:
                self.exit()
            return
        session = login.session
        account = Account(login.url, session.user.email)
        self.token_store.save(account, session.token)
        self._start_account(account, session.token)
        self.user = session.user
        self._signed_in_as()

    def _signed_in_as(self) -> None:
        self.main.show_list()
        self._show_account()
        self.query_one(YafsView).load()

    def _go_offline(self, detail: str) -> None:
        """Hide the list and everything that needs the server until a retry succeeds."""
        self.main.show_offline(server_name(self.url), detail)

    def switch_account(self, account: Account) -> None:
        """Use another stored account, on whichever server it is; the settings screen and s are the ways in."""
        if account == self.account and self.client.token:
            return
        self.token_store.select(account)
        self._start_account(account, self.token_store.token(account))
        self._check_token()

    def action_next_account(self) -> None:
        """Move to the next stored account, wrapping around, so s alone cycles through them all."""
        accounts = self.token_store.accounts()
        if len(accounts) < 2:
            return
        index = accounts.index(self.account) if self.account in accounts else -1
        account = accounts[(index + 1) % len(accounts)]
        self.switch_account(account)
        self.notify(f"Switched to {account.label}")

    def add_account(self) -> None:
        """Log in to one more account; the current one stays stored."""
        self._ask_login(cancel_label="Cancel")

    def _start_account(self, account: Account | None, token: str) -> None:
        """Point the client at an account, and its server, and drop what was on screen for the last one."""
        self.account = account
        if account is not None:
            self.url = account.url
            self.servers = self.config.servers_with(self.url)
        self.client.base_url = self.url
        self.client.token = token
        self.user = None
        self.client.score = None
        self.main.reset()
        self._show_account()

    def _use_next_account(self, message: str) -> None:
        """After a token is gone, move to another stored account, or ask to log in."""
        accounts = self.token_store.accounts()
        if accounts:
            if message:
                self.notify(message, severity="warning")
            self.switch_account(self.token_store.current() or accounts[0])
        else:
            self._ask_login(message)

    def _show_account(self) -> None:
        email = self.account.email if self.account else ""
        # Only a non-production server is worth calling out
        server = server_name(self.url) if self.url != DEFAULT_URL else ""
        self.query_one(YafHeader).show_account(email, server)

    def confirm_sign_out(self) -> None:
        """Ask before signing out; the settings screen is the way in."""
        if not self.client.token:
            return
        who = self.account.label if self.account else self.url
        dialog = ConfirmDialog(
            f"You are signed in as {who}",
            title="Sign Out",
            confirm_label="Sign out",
            cancel_label="Cancel",
        )
        self.push_screen(dialog, lambda confirmed: self._sign_out() if confirmed else None)

    @work(exclusive=True)
    async def _sign_out(self) -> None:
        try:
            await asyncio.to_thread(self.client.logout)
        except (ApiError, ApiConnectionError):
            pass  # Forgetting the token locally is what signs out; revoking it is best effort
        self.token_store.clear(self.account)
        self._start_account(None, "")
        self._use_next_account("")
