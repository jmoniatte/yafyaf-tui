"""Fixtures and helpers shared by the app tests."""

import contextlib
import shlex
import sys
from unittest.mock import patch

from datetime import date

from tui_kit.header_notification import HeaderNotification

from yafyaf_tui.api import (
    ApiConnectionError,
    User,
    Yaf,
    YafPage,
    Tag,
)
from yafyaf_tui.app import YafyafApp
from yafyaf_tui.accounts import Account
from yafyaf_tui.widgets import YafsTable

ME = User(id="abc", email="me@example.com")
SAYINGS = User(id="say", email="sayings@example.com")
OTHER = User(id="xyz", email="other@example.com")
URL = "http://localhost:3000"
ME_ACCOUNT = Account(URL, ME.email)
SAYINGS_ACCOUNT = Account(URL, SAYINGS.email)
OTHER_ACCOUNT = Account(URL, OTHER.email)
YAFS = (
    Yaf(id="y1", content="First yaf\nwith a second line", date=date(2026, 9, 13)),
    Yaf(id="y2", content="Second yaf", date=date(2026, 9, 12)),
)
ONE_PAGE = YafPage(yafs=YAFS, records_count=2)


@contextlib.contextmanager
def patched_editor(editor: str):
    """Run editor in place of the user's editor; yields how many times the app resumed after it."""
    resumed = []

    @contextlib.contextmanager
    def suspend(_app):
        # Like Textual's suspend, the TUI only comes back if the block does not raise
        yield
        resumed.append(True)

    # The headless test driver cannot suspend, and these editors do not need the terminal
    with patch.dict("os.environ", {"VISUAL": editor}), patch("yafyaf_tui.app.YafyafApp.suspend", suspend):
        yield resumed


def python_editor(code: str) -> str:
    """An editor command that runs Python on the draft, whose path is sys.argv[1]."""
    return shlex.join([sys.executable, "-c", code])


def no_server():
    """Fail every request a test did not patch, as if no server were running.

    Otherwise a server running at URL (a local Rails, say) answers them, and its replies, which
    carry no saying or score, overwrite what the test set up.
    """
    error = ApiConnectionError(f"Cannot reach {URL}: the tests reach no server")
    return patch("yafyaf_tui.api.client.YafyafClient.request", side_effect=error)


def patched_me():
    return patch("yafyaf_tui.api.client.YafyafClient.me", return_value=ME)


def patched_list(*pages: YafPage):
    if not pages:
        return patch("yafyaf_tui.api.client.YafyafClient.list_yafs", return_value=ONE_PAGE)
    return patch("yafyaf_tui.api.client.YafyafClient.list_yafs", side_effect=list(pages))


def patched_tags(*tags: Tag):
    return patch("yafyaf_tui.api.client.YafyafClient.list_tags", return_value=list(tags))


def patched_get(*yafs: Yaf, error: Exception | None = None):
    """The server's copy of each yaf: the given ones, else the list's."""
    by_id = {yaf.id: yaf for yaf in (*YAFS, *yafs)}
    return patch("yafyaf_tui.api.client.YafyafClient.get_yaf", side_effect=error or by_id.__getitem__)


def row_text(table: YafsTable, row: int) -> list[str]:
    return [str(cell) for cell in table.get_row_at(row)]


def header_message(app: YafyafApp) -> str:
    notification = app.screen.query_one(HeaderNotification)
    return notification.render().plain if notification.display else ""


async def settle(app: YafyafApp, pilot) -> None:
    """Let workers finish, including ones started by callbacks of earlier workers, then let the UI catch up."""
    while True:
        await pilot.pause()
        if not any(worker.is_running for worker in app.workers):
            break
        await app.workers.wait_for_complete()
    await pilot.pause()


