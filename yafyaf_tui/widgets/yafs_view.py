import asyncio
import re

from rich.style import Style
from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Input, Static

from ..api import ApiConnectionError, ApiError, Yaf, YafPage, YafyafClient
from ..shortcuts import ACTIONS, GENERAL
from .dashed_rule import DashedRule


DATE_WIDTH = 10
HEADING = re.compile(r"#{1,6}\s+(.*?)(?:\s+#+)?\s*$")
# A markdown link, or a bare URL; trailing punctuation and closing brackets are left out of a bare URL
LINK = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<target>[^)\s]+)\)|(?P<url>https?://[^\s<>()\[\]]*[^\s<>()\[\].,;:!?'\"])")


def summary_text(
    summary: str,
    link_color: str = "",
    hovered_link: str | None = None,
    *,
    heading_color: str = "",
) -> Text:
    """Show links in the link color, markdown ones by their label, underlining the hovered one.

    A markdown heading ("# Title", "## Title") loses its # marks and takes the heading color.
    """
    heading = HEADING.match(summary)
    if heading:
        summary = heading.group(1)
    text = Text(style=heading_color if heading and heading_color else "")
    end = 0
    for match in LINK.finditer(summary):
        url = match.group("target") or match.group("url")
        text.append(summary[end : match.start()])
        text.append(
            match.group("label") or url,
            style=Style(color=link_color or None, underline=url == hovered_link, link=url),
        )
        end = match.end()
    text.append(summary[end:])
    return text


class YafsTable(DataTable):
    """The list of yafs; rows are keyed by yaf id. Links in a summary open in the browser, like Flotte's URLs."""

    BINDINGS = [
        Binding("enter", "select_cursor", "Edit yaf", show=False, group=ACTIONS),
        Binding("j", "cursor_down", "Move down", show=False, group=GENERAL),
        Binding("k", "cursor_up", "Move up", show=False, group=GENERAL),
    ]

    def __init__(self, date_color: str = "", link_color: str = "", heading_color: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._date_color = date_color
        self._link_color = link_color
        self._heading_color = heading_color
        self._summaries: dict[str, str] = {}
        # (yaf id, url) under the pointer
        self._hovered: tuple[str, str] | None = None

    def add_yaf(self, yaf: Yaf) -> None:
        self._summaries[yaf.id] = yaf.summary
        self.add_row(*self._cells(yaf), key=yaf.id)

    def update_yaf(self, yaf: Yaf) -> None:
        self._summaries[yaf.id] = yaf.summary
        date_cell, summary_cell = self._cells(yaf)
        self.update_cell(yaf.id, "date", date_cell)
        self.update_cell(yaf.id, "summary", summary_cell)

    def clear(self, columns: bool = False) -> "YafsTable":
        self._summaries = {}
        self._hovered = None
        return super().clear(columns)

    def _cells(self, yaf: Yaf) -> tuple[Text, Text]:
        # Text, not str: the table reads strings as markup, which eats "[link]" style brackets in a summary
        return Text(yaf.date.isoformat(), style=self._date_color), self._summary_cell(yaf.id)

    def _summary_cell(self, yaf_id: str) -> Text:
        hovered = self._hovered[1] if self._hovered and self._hovered[0] == yaf_id else None
        return summary_text(self._summaries[yaf_id], self._link_color, hovered, heading_color=self._heading_color)

    def _link_at(self, event: events.MouseEvent) -> tuple[str, str] | None:
        row = event.style.meta.get("row")
        if event.style.link and isinstance(row, int) and 0 <= row < self.row_count:
            return self.ordered_rows[row].key.value, event.style.link
        return None

    def on_mouse_move(self, event: events.MouseMove) -> None:
        # The highlight follows the pointer as it does with the arrow keys, links included
        row = event.style.meta.get("row")
        if isinstance(row, int) and 0 <= row < self.row_count and row != self.cursor_row:
            self.move_cursor(row=row)
        self._set_hovered(self._link_at(event))

    def on_leave(self, event: events.Leave) -> None:
        self._set_hovered(None)

    def _set_hovered(self, hovered: tuple[str, str] | None) -> None:
        if hovered == self._hovered:
            return
        previous, self._hovered = self._hovered, hovered
        for yaf_id in {pair[0] for pair in (previous, hovered) if pair}:
            if yaf_id in self._summaries:
                self.update_cell(yaf_id, "summary", self._summary_cell(yaf_id))

    async def _on_click(self, event: events.Click) -> None:
        link = self._link_at(event)
        row = event.style.meta.get("row")
        if link is None and not (isinstance(row, int) and 0 <= row < self.row_count):
            return
        # Handled here rather than by DataTable, which only opens a row on a second click in the same cell
        event.prevent_default()
        event.stop()
        if link is not None:
            self.app.open_url(link[1])
        else:
            self.move_cursor(row=row)
            self.action_select_cursor()


class YafOpened(Message):
    """The user asked to see one yaf in full."""

    def __init__(self, yaf: Yaf) -> None:
        super().__init__()
        self.yaf = yaf


class NewYafRequested(Message):
    """The user asked to write a new yaf."""


class YafsView(Vertical):
    """Search box and New Yaf button, then the result list with the yaf count in its header, paged from the API."""

    BINDINGS = [
        Binding("n", "new_yaf", "New yaf", group=ACTIONS),
        Binding("slash", "search", "Search", key_display="/", group=ACTIONS),
        Binding("r", "refresh", "Refresh", group=ACTIONS),
    ]

    def __init__(
        self,
        client: YafyafClient,
        date_color: str = "",
        link_color: str = "",
        heading_color: str = "",
        **kwargs,
    ) -> None:
        super().__init__(id="yafs-view", **kwargs)
        self._client = client
        self._colors = {"date_color": date_color, "link_color": link_color, "heading_color": heading_color}
        self._query = ""
        self._next_page: dict | None = None
        self._loading = False
        self.yafs: list[Yaf] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="yafs-controls"):
            yield Input(placeholder="Search yafs", id="search")
            yield Button("New Yaf", id="btn-new-yaf")
        # The table's own header cannot hold the count, so it is hidden and drawn here instead
        with Horizontal(id="yafs-header"):
            yield Static("Date", id="yafs-header-date")
            yield Static("Yaf", id="yafs-header-summary")
            yield Static("", id="yafs-status")
        yield DashedRule(id="yafs-header-rule")
        # "renderable" keeps the gray date on the highlighted row too, as in Flotte
        yield YafsTable(
            **self._colors,
            id="yafs-table",
            cursor_type="row",
            zebra_stripes=False,
            show_header=False,
            cursor_foreground_priority="renderable",
        )

    def on_mount(self) -> None:
        table = self.query_one(YafsTable)
        table.add_column("Date", key="date", width=DATE_WIDTH)
        table.add_column("Yaf", key="summary")
        # Line the header labels up with the cells, which are padded on both sides
        self.query_one("#yafs-header-date").styles.width = DATE_WIDTH + 2 * table.cell_padding
        for label in self.query("#yafs-header-date, #yafs-header-summary"):
            label.styles.padding = (0, table.cell_padding)
        table.focus()

    def load(self, query: str | None = None) -> None:
        """Start over from page one, optionally with a new search."""
        if query is not None:
            self._query = query.strip()
        self.yafs = []
        self._next_page = None
        self.query_one(YafsTable).clear()
        self._set_status("Loading...")
        self._fetch(page=1)

    def reset(self) -> None:
        """Forget the search and the loaded yafs, e.g. when the user signs out."""
        self.workers.cancel_node(self)
        self._query = ""
        self._loading = False
        self.yafs = []
        self._next_page = None
        self.query_one("#search", Input).value = ""
        self.query_one(YafsTable).clear()
        self._set_status("")

    @on(Button.Pressed, "#btn-new-yaf")
    def action_new_yaf(self) -> None:
        # A clicked button keeps focus; hand it back to the list the editor returns to
        self.query_one(YafsTable).focus()
        self.post_message(NewYafRequested())

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_refresh(self) -> None:
        self.load()

    @on(Input.Submitted, "#search")
    def _search_submitted(self, event: Input.Submitted) -> None:
        self.query_one(YafsTable).focus()
        if event.value.strip() != self._query:
            self.load(event.value)

    def on_key(self, event) -> None:
        # Escape in the search box goes back to the list without changing the search
        if event.key == "escape" and self.query_one("#search", Input).has_focus:
            event.stop()
            self.query_one(YafsTable).focus()

    @on(DataTable.RowSelected)
    def _open_selected(self, event: DataTable.RowSelected) -> None:
        if event.cursor_row < len(self.yafs):
            self.post_message(YafOpened(self.yafs[event.cursor_row]))

    @on(DataTable.RowHighlighted)
    def _maybe_fetch_more(self, event: DataTable.RowHighlighted) -> None:
        if self._next_page is None or self._loading:
            return
        if event.cursor_row >= len(self.yafs) - 1:
            self._fetch(page=int(self._next_page.get("page", 1)))

    @work(exclusive=True)
    async def _fetch(self, page: int) -> None:
        self._loading = True
        try:
            result = await asyncio.to_thread(self._client.list_yafs, self._query, page)
        except (ApiError, ApiConnectionError) as error:
            self._set_status(str(error))
            self.notify(str(error), severity="error")
            return
        finally:
            self._loading = False
        self._append(result)

    def _append(self, result: YafPage) -> None:
        table = self.query_one(YafsTable)
        for yaf in result.yafs:
            table.add_yaf(yaf)
        self.yafs.extend(result.yafs)
        self._next_page = result.next_page
        self._set_status(self._describe(result.records_count))

    def replace(self, yaf: Yaf) -> None:
        """Show a saved yaf in its row without reloading, so the cursor stays put."""
        for index, shown in enumerate(self.yafs):
            if shown.id == yaf.id:
                self.yafs[index] = yaf
                self.query_one(YafsTable).update_yaf(yaf)
                return

    def _describe(self, total: int) -> str:
        noun = "yaf" if total == 1 else "yafs"
        shown = f"{len(self.yafs)} of {total} {noun}" if len(self.yafs) < total else f"{total} {noun}"
        return f"{shown} matching '{self._query}'" if self._query else shown

    def _set_status(self, text: str) -> None:
        self.query_one("#yafs-status", Static).update(text)
