from ouikit.panel import PanelScreen
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Select, Static

ADD_ACCOUNT = "+"


class SettingsScreen(PanelScreen):
    """The signed-in account; the theme is picked with t and the shortcuts are on the Help panel."""

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-panel"):
            yield Static("Settings", id="dialog-title")
            yield Static("", id="title-separator")

            with Horizontal(classes="settings-row", id="settings-account-row"):
                yield Static("Account", classes="settings-label")
                # Every stored account, on every server; picking one moves the app there
                accounts = self.app.token_store.accounts()
                if self.app.account in accounts:
                    yield Select(
                        options=[(account.label, account) for account in accounts] + [("Add account...", ADD_ACCOUNT)],
                        value=self.app.account,
                        id="account-selector",
                        allow_blank=False,
                    )
                else:
                    yield Static("Not signed in", id="settings-email")
                if self.app.client.token:
                    yield Button("Sign out", id="btn-sign-out")

            yield Static("", id="panel-footer-spacer")
            with Horizontal(id="panel-footer"):
                yield Button("Close", id="btn-close")

    @on(Select.Changed, "#account-selector")
    def _account_changed(self, event: Select.Changed) -> None:
        event.stop()
        if event.value == ADD_ACCOUNT:
            # Close first, so the login screen is not stacked on this one
            self.dismiss()
            self.app.call_later(self.app.add_account)
        else:
            self.app.switch_account(event.value)

    @on(Button.Pressed, "#btn-sign-out")
    def _sign_out(self, event: Button.Pressed) -> None:
        event.stop()
        # Close first, so the confirmation and the login screen behind it are not stacked on this one
        self.dismiss()
        self.app.call_later(self.app.confirm_sign_out)
