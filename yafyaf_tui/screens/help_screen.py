from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from .. import REPOSITORY_URL, __version__
from .. import shortcuts as shortcut_help
from ..widgets.web_link import WebLink


class HelpScreen(ModalScreen):
    """Modal screen listing every documented keyboard shortcut."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    def _sections(self) -> list[tuple[str, tuple[shortcut_help.Shortcut, ...]]]:
        """Read the shortcuts off the bindings, so the two cannot drift."""
        return [
            (section, shortcut_help.for_section(section, self.app.BINDINGS))
            for section in shortcut_help.SECTIONS
        ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Keyboard Shortcuts", id="dialog-title")
            yield Static("", id="title-separator")

            with Horizontal(id="help-sections"):
                for section, shortcuts in self._sections():
                    with Vertical(id=f"help-{section.lower()}", classes="help-section"):
                        yield Static(section.upper(), classes="section-title")
                        for shortcut in shortcuts:
                            with Horizontal(classes="shortcut-row"):
                                yield Static(shortcut.key, classes="shortcut-key")
                                yield Static(shortcut.description, classes="shortcut-desc")

            yield Static("", id="help-footer-spacer")
            with Horizontal(id="help-footer"):
                yield Static("", classes="spacer")
                yield WebLink(REPOSITORY_URL, label="YafYaf TUI", id="help-repository")
                yield Static(f"v{__version__}", id="help-version")

    def on_key(self, event) -> None:
        self.dismiss()

    def on_click(self, event) -> None:
        self.dismiss()
