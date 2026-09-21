from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Markdown, Static

from ..api import Yaf
from ..shortcuts import ACTIONS
from .yaf_markdown import YafMarkdown
from .yafs_view import EditRequested


class ViewClosed(Message):
    """The user asked to go back to the list."""


class YafDetail(Vertical):
    """One yaf rendered as markdown, in place of the list; the keys that edit a yaf work here too."""

    BINDINGS = [
        Binding("escape", "close", "Back to the list", group=ACTIONS),
        # Takes q from the app while the view is up, so it leaves the view rather than the app
        Binding("q", "close", "Back to the list", group=ACTIONS),
        Binding("y", "copy", "Copy the selection, or the yaf", group=ACTIONS),
        Binding("e", "edit", "Edit yaf", show=False),
        Binding("shift+enter", "edit", "Edit yaf", show=False),
        Binding("j", "scroll_down", "Scroll down", show=False),
        Binding("k", "scroll_up", "Scroll up", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(id="yaf-detail", **kwargs)
        self.yaf: Yaf | None = None

    def compose(self) -> ComposeResult:
        # The full date and the yaf's API id at the right edge, then a blank line before the content
        with Horizontal(id="yaf-detail-header"):
            yield Static("", id="yaf-detail-date")
            yield Static("", id="yaf-detail-id")
        with VerticalScroll(id="yaf-detail-scroll"):
            yield YafMarkdown(id="yaf-detail-markdown")

    def show(self, yaf: Yaf) -> None:
        self.yaf = yaf
        day = yaf.date
        self.query_one("#yaf-detail-date", Static).update(f"{day:%A}, {day:%B} {day.day}, {day.year}")
        self.query_one("#yaf-detail-id", Static).update(yaf.id)
        self.query_one(Markdown).update(yaf.content)
        scroll = self.query_one(VerticalScroll)
        scroll.scroll_home(animate=False)
        self.display = True
        scroll.focus()

    def action_close(self) -> None:
        self.post_message(ViewClosed())

    def action_edit(self) -> None:
        if self.yaf is not None:
            self.post_message(EditRequested(self.yaf))

    def action_copy(self) -> None:
        """Copy the text selected with the mouse, or the whole yaf when nothing is selected."""
        if self.yaf is None:
            return
        selection = self.screen.get_selected_text()
        self.app.copy_to_clipboard(selection or self.yaf.content)
        self.notify("Selection copied" if selection else "Yaf copied")

    def action_scroll_down(self) -> None:
        self.query_one(VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one(VerticalScroll).scroll_up()
