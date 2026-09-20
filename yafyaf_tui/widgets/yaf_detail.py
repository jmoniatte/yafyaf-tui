import ast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content, Span
from textual.message import Message
from textual.style import Style
from textual.widgets import Markdown, Static
from textual.widgets.markdown import MarkdownBlock

from ..api import Yaf
from ..shortcuts import ACTIONS
from .yafs_view import EditRequested


class ViewClosed(Message):
    """The user asked to go back to the list."""


def _with_hyperlink(style: Style | str) -> Style | str:
    """Textual only gives a markdown link a click action; add the terminal hyperlink the list's links carry."""
    if isinstance(style, str) or style.link is not None:
        return style
    action = style.meta.get("@click", "")
    if not action.startswith("link("):
        return style
    return style + Style(link=ast.literal_eval(action[5:-1]))


class _LinkedBlock:
    def _token_to_content(self, token) -> Content:
        content = super()._token_to_content(token)
        spans = [Span(span.start, span.end, _with_hyperlink(span.style)) for span in content.spans]
        return Content(content.plain, spans)


class YafMarkdown(Markdown):
    """Markdown whose links the terminal can open itself, as it can the list's, not only through the app."""

    _linked: dict[type[MarkdownBlock], type[MarkdownBlock]] = {}

    def get_block_class(self, block_name: str) -> type[MarkdownBlock]:
        block = super().get_block_class(block_name)
        if block not in self._linked:
            self._linked[block] = type(block.__name__, (_LinkedBlock, block), {})
        return self._linked[block]


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
        with VerticalScroll(id="yaf-detail-scroll"):
            yield YafMarkdown(id="yaf-detail-markdown")
        # Where the saying sits under the list
        with Horizontal(id="yaf-detail-footer"):
            yield Static("", id="yaf-detail-date")
            yield Static("", id="yaf-detail-id")

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
