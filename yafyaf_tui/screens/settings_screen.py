from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Select, Static

from .. import REPOSITORY_URL, __version__
from .. import shortcuts as shortcut_help
from ..theme import list_themes, resolve_theme
from ..widgets.dashed_rule import DashedRule
from ..widgets.web_link import WebLink
from ..widgets.yafs_view import YafsTable, YafsView


class SettingsScreen(ModalScreen):
    """Modal screen for the theme, the signed-in account, and the documented shortcuts."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    def _sections(self) -> list[tuple[str, tuple[shortcut_help.Shortcut, ...]]]:
        """Read the shortcuts off the bindings, so the two cannot drift."""
        sources = (YafsView.BINDINGS, YafsTable.BINDINGS, self.app.BINDINGS)
        return [
            (section, shortcut_help.for_section(section, *sources))
            for section in shortcut_help.SECTIONS
        ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Settings", id="dialog-title")
            yield Static("", id="title-separator")

            with Horizontal(classes="settings-row"):
                yield Static("Theme", classes="settings-label")
                yield Select(
                    options=[(name, name) for name in list_themes()],
                    value=resolve_theme(self.app.config.theme),
                    id="theme-selector",
                    allow_blank=False,
                )

            with Horizontal(classes="settings-row", id="settings-account-row"):
                yield Static("Account", classes="settings-label")
                # The token, not the user: an unreachable server leaves a token whose owner is unknown,
                # and that is exactly when signing out to clear it matters
                token = self.app.client.token
                user = self.app.user
                if user:
                    account = user.email
                elif token:
                    account = "Signed in, server unreachable"
                else:
                    account = "Not signed in"
                yield Static(account, id="settings-email", markup=False)
                if token:
                    yield Button("Sign out", id="btn-sign-out")

            yield DashedRule(id="settings-separator")

            with Horizontal(id="shortcuts-sections"):
                for section, shortcuts in self._sections():
                    with Vertical(id=f"shortcuts-{section.lower()}", classes="shortcuts-section"):
                        yield Static(section.upper(), classes="section-title")
                        for shortcut in shortcuts:
                            with Horizontal(classes="shortcut-row"):
                                yield Static(shortcut.key, classes="shortcut-key")
                                yield Static(shortcut.description, classes="shortcut-desc")

            yield Static("", id="settings-footer-spacer")
            with Horizontal(id="settings-footer"):
                yield Static("esc to close", classes="spacer")
                yield WebLink(REPOSITORY_URL, label="YafYaf TUI", id="settings-repository")
                yield Static(__version__, id="settings-version")

    @on(Select.Changed, "#theme-selector")
    def _theme_changed(self, event: Select.Changed) -> None:
        event.stop()
        if event.value is not Select.BLANK:
            self.app.set_theme(event.value)

    @on(Button.Pressed, "#btn-sign-out")
    def _sign_out(self, event: Button.Pressed) -> None:
        event.stop()
        # Close first, so the confirmation and the login screen behind it are not stacked on this one
        self.dismiss()
        self.app.call_later(self.app.confirm_sign_out)

    def on_click(self, event) -> None:
        """Dismiss on a click outside the dialog, but let the dropdown work."""
        if event.widget is self:
            self.dismiss()
