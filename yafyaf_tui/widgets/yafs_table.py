"""The list's table: one row per yaf, the summary rendered as Rich text with clickable links."""

import re
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable

from ..api import Yaf
from ouikit.shortcuts import ACTIONS, GENERAL

DATE_WIDTH = 10
HEADING = re.compile(r"#{1,6}\s+(.*?)(?:\s+#+)?\s*$")
# A markdown link, or a bare URL; trailing punctuation and closing brackets are left out of a bare URL
LINK = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<target>[^)\s]+)\)|(?P<url>https?://[^\s<>()\[\]]*[^\s<>()\[\].,;:!?'\"])")
# The server's rule for a tag: a #word starting with a letter, not glued to what precedes it
TAG = re.compile(r"(?<![\w&/#-])#(?P<name>[a-z][a-z0-9_-]*)", re.IGNORECASE)
INLINE_CODE = re.compile(r"`[^`\n]*`")


def find_tags(text: str) -> list[tuple[int, int, str]]:
    """(start, end, name) of every tag in text, skipping inline code, names lowercased."""
    code = [(m.start(), m.end()) for m in INLINE_CODE.finditer(text)]
    return [
        (m.start(), m.end(), m.group("name").lower().rstrip("-"))
        for m in TAG.finditer(text)
        if not any(start <= m.start() < end for start, end in code)
    ]


def summary_text(
    summary: str,
    link_color: str = "",
    hovered_link: str | None = None,
    *,
    heading_color: str = "",
    tag_color: str = "",
) -> Text:
    """Show links in the link color, markdown ones by their label, underlining the hovered one.

    A markdown heading ("# Title", "## Title") loses its # marks and takes the heading color.
    Tags take the tag color and carry their name in the style's meta, so a click can filter on them.
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
    for start, stop, name in find_tags(text.plain):
        text.stylize(Style(color=tag_color or None, meta={"tag": name}), start, stop)
    return text


@dataclass(frozen=True, slots=True)
class ListColors:
    """The palette entries the list bakes into Rich text, where TCSS variables do not reach."""

    date: str = ""
    link: str = ""
    heading: str = ""
    tag: str = ""


class TagSelected(Message):
    """The user picked a tag, in a row, in a yaf or from the dropdown, to filter the list on."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name


class YafsTable(DataTable):
    """The list of yafs; rows are keyed by yaf id. Links in a summary open in the browser, like Flotte's URLs."""

    BINDINGS = [
        Binding("enter", "select_cursor", "View yaf", show=False, group=ACTIONS),
        Binding("j", "cursor_down", "Move down", show=False, group=GENERAL),
        Binding("k", "cursor_up", "Move up", show=False, group=GENERAL),
    ]

    def __init__(self, colors: ListColors, **kwargs) -> None:
        super().__init__(**kwargs)
        self._colors = colors
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

    def set_colors(self, colors: ListColors) -> None:
        self._colors = colors

    def clear(self, columns: bool = False) -> "YafsTable":
        self._summaries = {}
        self._hovered = None
        return super().clear(columns)

    def _cells(self, yaf: Yaf) -> tuple[Text, Text]:
        # Text, not str: the table reads strings as markup, which eats "[link]" style brackets in a summary
        return Text(yaf.date.isoformat(), style=self._colors.date), self._summary_cell(yaf.id)

    def _summary_cell(self, yaf_id: str) -> Text:
        hovered = self._hovered[1] if self._hovered and self._hovered[0] == yaf_id else None
        return summary_text(
            self._summaries[yaf_id], self._colors.link, hovered, heading_color=self._colors.heading, tag_color=self._colors.tag
        )

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
        tag = event.style.meta.get("tag")
        row = event.style.meta.get("row")
        if link is None and tag is None and not (isinstance(row, int) and 0 <= row < self.row_count):
            return
        # Handled here rather than by DataTable, which only opens a row on a second click in the same cell
        event.prevent_default()
        event.stop()
        if link is not None:
            self.app.open_url(link[1])
        elif tag is not None:
            self.post_message(TagSelected(tag))
        else:
            self.move_cursor(row=row)
            self.action_select_cursor()
