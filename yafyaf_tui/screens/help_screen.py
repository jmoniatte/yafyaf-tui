from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from .. import REPOSITORY_URL, __version__
from .. import shortcuts as shortcut_help
from ..widgets.web_link import WebLink
from ..widgets.yaf_detail import YafDetail
from ..widgets.yafs_table import YafsTable
from ..widgets.yafs_view import YafsView
from .panel import PanelScreen


class HelpScreen(PanelScreen):
    """The documented shortcuts, read off the bindings so the two cannot drift, with the version and the repository."""

    def _sections(self) -> list[tuple[str, tuple[shortcut_help.Shortcut, ...]]]:
        sources = (YafsView.BINDINGS, YafsTable.BINDINGS, YafDetail.BINDINGS, self.app.BINDINGS)
        return [(section, shortcut_help.for_section(section, *sources)) for section in shortcut_help.SECTIONS]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Help", id="dialog-title")
            yield Static("", id="title-separator")
            with Horizontal(id="shortcuts-sections"):
                for section, shortcuts in self._sections():
                    with Vertical(id=f"shortcuts-{section.lower()}", classes="shortcuts-section"):
                        yield Static(section.upper(), classes="section-title")
                        for shortcut in shortcuts:
                            with Horizontal(classes="shortcut-row"):
                                yield Static(shortcut.key, classes="shortcut-key")
                                yield Static(shortcut.description, classes="shortcut-desc")
            yield Static("", id="panel-footer-spacer")
            with Horizontal(id="panel-footer"):
                yield Button("Close", id="btn-close")
                yield Static("", classes="spacer")
                yield WebLink(REPOSITORY_URL, label="YafYaf TUI", id="panel-repository")
                yield Static(__version__, id="panel-version")
