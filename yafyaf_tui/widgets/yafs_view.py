import asyncio

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Input, Static

from ..api import ApiConnectionError, ApiError, Yaf, YafPage, YafyafClient
from ..shortcuts import ACTIONS, GENERAL


class YafsTable(DataTable):
    """The list of yafs; rows are keyed by yaf id."""

    BINDINGS = [
        Binding("enter", "select_cursor", "Open yaf", show=False, group=ACTIONS),
        Binding("j", "cursor_down", "Move down", show=False, group=GENERAL),
        Binding("k", "cursor_up", "Move up", show=False, group=GENERAL),
    ]


class YafOpened(Message):
    """The user asked to see one yaf in full."""

    def __init__(self, yaf: Yaf) -> None:
        super().__init__()
        self.yaf = yaf


class YafsView(Vertical):
    """Search box, result list, and a status line, fed by the API one page at a time."""

    BINDINGS = [
        Binding("slash", "search", "Search", key_display="/", group=ACTIONS),
        Binding("r", "refresh", "Refresh", group=ACTIONS),
    ]

    def __init__(self, client: YafyafClient, **kwargs) -> None:
        super().__init__(id="yafs-view", **kwargs)
        self._client = client
        self._query = ""
        self._next_page: dict | None = None
        self._loading = False
        self.yafs: list[Yaf] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search yafs", id="search")
        yield YafsTable(id="yafs-table", cursor_type="row", zebra_stripes=False)
        yield Static("", id="yafs-status")

    def on_mount(self) -> None:
        table = self.query_one(YafsTable)
        table.add_column("Date", key="date", width=10)
        table.add_column("Yaf", key="summary")
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
            self.notify(str(error), title="Yafs", severity="error")
            return
        finally:
            self._loading = False
        self._append(result)

    def _append(self, result: YafPage) -> None:
        table = self.query_one(YafsTable)
        for yaf in result.yafs:
            table.add_row(yaf.date.isoformat(), yaf.summary, key=yaf.id)
        self.yafs.extend(result.yafs)
        self._next_page = result.next_page
        self._set_status(self._describe(result.records_count))

    def _describe(self, total: int) -> str:
        noun = "yaf" if total == 1 else "yafs"
        shown = f"{len(self.yafs)} of {total} {noun}" if len(self.yafs) < total else f"{total} {noun}"
        return f"{shown} matching '{self._query}'" if self._query else shown

    def _set_status(self, text: str) -> None:
        self.query_one("#yafs-status", Static).update(text)
