import asyncio

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Input, Select, Static

from ..api import ApiConnectionError, ApiError, Tag, Yaf, YafPage, YafyafClient
from ouikit.shortcuts import ACTIONS
from .dashed_rule import DashedRule
from .yafs_table import DATE_WIDTH, ListColors, YafsTable


class YafOpened(Message):
    """The user asked to see one yaf in full."""

    def __init__(self, yaf: Yaf) -> None:
        super().__init__()
        self.yaf = yaf


class EditRequested(Message):
    """The user asked to edit one yaf in the editor."""

    def __init__(self, yaf: Yaf) -> None:
        super().__init__()
        self.yaf = yaf


class NewYafRequested(Message):
    """The user asked to write a new yaf."""


class YafsView(Vertical):
    """Search box and New Yaf button, then the result list with the yaf count in its header, paged from the API."""

    BINDINGS = [
        Binding("n", "new_yaf", "New yaf", group=ACTIONS),
        Binding("e", "edit_yaf", "Edit yaf", group=ACTIONS),
        # Only terminals with the kitty keyboard protocol can tell this from enter; e works everywhere
        Binding("shift+enter", "edit_yaf", "Edit yaf", key_display="⇧+enter", group=ACTIONS),
        Binding("slash", "search", "Search", key_display="/", group=ACTIONS),
        Binding("number_sign", "tags", "Tags", key_display="#", group=ACTIONS),
        Binding("r", "refresh", "Refresh", group=ACTIONS),
        Binding("y", "copy_yaf", "Copy yaf", group=ACTIONS),
    ]

    def __init__(self, client: YafyafClient, colors: ListColors | None = None, **kwargs) -> None:
        super().__init__(id="yafs-view", **kwargs)
        self._client = client
        self._colors = colors or ListColors()
        self._query = ""
        self._next_page: dict | None = None
        self._loading = False
        self.yafs: list[Yaf] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="yafs-controls"):
            yield Input(placeholder="Search yafs", id="search")
            # Picking a tag types "#name" into the search; the dropdown itself never stays selected
            yield Select([], prompt="Tags", id="tag-selector")
            yield Button("New Yaf", id="btn-new-yaf")
        # The table's own header cannot hold the count, so it is hidden and drawn here instead
        with Horizontal(id="yafs-header"):
            yield Static("Date", id="yafs-header-date")
            yield Static("Yaf", id="yafs-header-summary")
            yield Static("", id="yafs-status")
        yield DashedRule(id="yafs-header-rule")
        # "renderable" keeps the gray date on the highlighted row too, as in Flotte
        yield YafsTable(
            self._colors,
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

    def set_colors(self, colors: ListColors) -> None:
        """Re-render the rows against a new palette; their colors are baked into Rich text."""
        self._colors = colors
        table = self.query_one(YafsTable)
        table.set_colors(colors)
        for yaf in self.yafs:
            table.update_yaf(yaf)

    def load(self, query: str | None = None) -> None:
        """Start over from page one, optionally with a new search."""
        if query is not None:
            self._query = query.strip()
        self.yafs = []
        self._next_page = None
        self.query_one(YafsTable).clear()
        self._set_status("Loading...")
        self._fetch(page=1)
        self._load_tags()

    def reset(self) -> None:
        """Forget the search and the loaded yafs, e.g. when the user signs out."""
        self.workers.cancel_node(self)
        self._query = ""
        self._loading = False
        self.yafs = []
        self._next_page = None
        self.query_one("#search", Input).value = ""
        self.query_one(YafsTable).clear()
        self._set_tags([])
        self._set_status("")

    @on(Button.Pressed, "#btn-new-yaf")
    def action_new_yaf(self) -> None:
        # A clicked button keeps focus; hand it back to the list the editor returns to
        self.query_one(YafsTable).focus()
        self.post_message(NewYafRequested())

    def selected_yaf(self) -> Yaf | None:
        """The highlighted yaf, or None while the list is empty."""
        row = self.query_one(YafsTable).cursor_row
        return self.yafs[row] if 0 <= row < len(self.yafs) else None

    def action_edit_yaf(self) -> None:
        if (yaf := self.selected_yaf()) is not None:
            self.post_message(EditRequested(yaf))

    def action_copy_yaf(self) -> None:
        if (yaf := self.selected_yaf()) is not None:
            self.app.copy_to_clipboard(yaf.content)
            self.notify("Yaf copied")

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_tags(self) -> None:
        selector = self.query_one("#tag-selector", Select)
        selector.focus()
        selector.action_show_overlay()

    def add_tag(self, name: str) -> None:
        """Add "#name" to the search and run it; how every way of picking a tag ends up."""
        search = self.query_one("#search", Input)
        token = f"#{name}"
        if token not in search.value.split():
            search.value = f"{search.value.rstrip()} {token}".strip()
        self.query_one(YafsTable).focus()
        self.load(search.value)

    @on(Select.Changed, "#tag-selector")
    def _tag_picked(self, event: Select.Changed) -> None:
        event.stop()
        if event.value is Select.NULL:
            return
        event.select.clear()
        self.add_tag(str(event.value))

    @work(exclusive=True, group="tags")
    async def _load_tags(self) -> None:
        try:
            tags = await asyncio.to_thread(self._client.list_tags)
        except (ApiError, ApiConnectionError):
            return  # The list's own request reports the problem
        self._set_tags(tags)

    def _set_tags(self, tags: list[Tag]) -> None:
        self.query_one("#tag-selector", Select).set_options((f"{tag.name} ({tag.count})", tag.name) for tag in tags)

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
    def _open_selected(self) -> None:
        if (yaf := self.selected_yaf()) is not None:
            self.post_message(YafOpened(yaf))

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
