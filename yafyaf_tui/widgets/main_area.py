"""The screen below the header: the yaf list, one yaf, or the offline notice, one at a time."""

from textual.app import ComposeResult
from textual.containers import Vertical

from ..api import Yaf, YafyafClient
from .echo import Echo
from .offline_notice import OfflineNotice
from .yaf_detail import YafDetail
from .yafs_table import ListColors, YafsTable
from .yafs_view import YafsView

PANES = (YafsView, YafDetail, OfflineNotice)


class MainArea(Vertical):
    """Shows one pane and hides the others; the saying sits under every pane but the yaf view.

    `viewing` is the yaf on show, or None: the editor returns to the view when it started there.
    """

    def __init__(self, client: YafyafClient, colors: ListColors) -> None:
        super().__init__(id="main-area")
        self._client = client
        self._colors = colors
        self.viewing: Yaf | None = None

    def compose(self) -> ComposeResult:
        yield YafsView(self._client, self._colors)
        yield YafDetail()
        yield OfflineNotice()
        yield Echo(self._client)

    def show_list(self) -> None:
        self._only(YafsView)
        self.query_one(YafsTable).focus()

    def show_yaf(self, yaf: Yaf) -> None:
        self._only(YafDetail)
        self.viewing = yaf
        self.query_one(YafDetail).show(yaf)

    def show_offline(self, server: str, detail: str) -> None:
        self._only(OfflineNotice)
        self.query_one(OfflineNotice).show(server, detail)

    def reset(self) -> None:
        """Drop what was loaded for the last account: the list, the search, the saying and the score."""
        self.query_one(Echo).sync()
        self.query_one(YafsView).reset()

    def _only(self, pane: type) -> None:
        self.viewing = None
        for kind in PANES:
            self.query_one(kind).display = kind is pane
        self.query_one(Echo).display = pane is not YafDetail
