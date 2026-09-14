from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Markdown, Static

from ..api import Yaf
from ..shortcuts import GENERAL
from ..widgets import AppHeader


class YafDetailScreen(Screen):
    """One yaf, rendered as the markdown it is written in."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back to the list", group=GENERAL),
        Binding("j", "scroll_down", "Scroll down", show=False),
        Binding("k", "scroll_up", "Scroll up", show=False),
    ]

    def __init__(self, yaf: Yaf) -> None:
        super().__init__()
        self.yaf = yaf

    def compose(self) -> ComposeResult:
        yield AppHeader(self.app.url)
        with Horizontal(id="yaf-detail-meta"):
            yield Static(self.yaf.date.isoformat(), id="yaf-detail-date")
            yield Static(self._edited(), id="yaf-detail-edited")
        with VerticalScroll(id="yaf-detail-body"):
            yield Markdown(self.yaf.content, id="yaf-detail-content")
        yield Static("esc back", id="status-line")

    def _edited(self) -> str:
        if not self.yaf.updated_at:
            return ""
        return f"edited {self.yaf.updated_at.astimezone().strftime('%Y-%m-%d %H:%M')}"

    def on_mount(self) -> None:
        self.query_one("#yaf-detail-body").focus()

    def action_scroll_down(self) -> None:
        self.query_one("#yaf-detail-body", VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one("#yaf-detail-body", VerticalScroll).scroll_up()
