import asyncio
import contextlib
import io
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from datetime import date

from textual.widgets import Button, Input, Markdown, Select, Static

from yafyaf_tui import __version__, shortcuts
from yafyaf_tui.__main__ import main
from yafyaf_tui.api import (
    ApiConnectionError,
    ApiError,
    AuthenticationError,
    NotFoundError,
    Session,
    User,
    Yaf,
    YafPage,
    YafyafClient,
)
from yafyaf_tui.app import YafyafApp
from yafyaf_tui.commands import new_yaf
from yafyaf_tui.config import DEFAULT_URL, Account, Config, TokenStore
from yafyaf_tui.screens import ConfirmDialog, LoginScreen, NotSavedDialog, SettingsScreen
from yafyaf_tui.screens.settings_screen import ADD_ACCOUNT
from yafyaf_tui.terminal_theme import TerminalReport
from yafyaf_tui.theme import load_palette
from yafyaf_tui.widgets import AccountLink, Echo, HeaderNotification, OfflineNotice, YafDetail, YafsTable, YafsView
from yafyaf_tui.widgets.yafs_view import DATE_WIDTH, summary_text

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


def patched_me():
    return patch("yafyaf_tui.api.client.YafyafClient.me", return_value=ME)


def patched_list(*pages: YafPage):
    if not pages:
        return patch("yafyaf_tui.api.client.YafyafClient.list_yafs", return_value=ONE_PAGE)
    return patch("yafyaf_tui.api.client.YafyafClient.list_yafs", side_effect=list(pages))


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


class MainTest(unittest.TestCase):
    def test_version_flag_exits_without_starting_the_tui(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"YafYaf TUI {__version__}")

    def test_url_flag_and_environment_pick_the_server(self) -> None:
        # The test runner may sit on a real tty; do not send it colour queries
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("yafyaf_tui.__main__.YafyafApp") as app_class,
            patch("yafyaf_tui.__main__.query_terminal", return_value=TerminalReport()) as query,
            patch("yafyaf_tui.__main__.TokenStore.default", return_value=TokenStore(Path(tmp) / "tokens.yaml")),
            patch("yafyaf_tui.__main__.load_config", return_value=Config()),
        ):
            with patch.dict("os.environ", {"YAFYAF_URL": ""}):
                main([])
            with patch.dict("os.environ", {"YAFYAF_URL": "http://localhost:3000"}):
                main([])
                main(["--url", "http://localhost:3100/", "--as", "me@example.com"])
        urls = [call.kwargs["url"] for call in app_class.call_args_list]
        self.assertEqual(urls, [DEFAULT_URL, "http://localhost:3000", "http://localhost:3100"])
        self.assertEqual([call.kwargs["account"] for call in app_class.call_args_list], [None, None, None])
        self.assertEqual([call.kwargs["login_email"] for call in app_class.call_args_list], ["", "", "me@example.com"])
        self.assertEqual(app_class.return_value.run.call_count, 3)
        self.assertEqual(query.call_count, 3)

    def test_new_command_creates_a_yaf_without_starting_the_tui(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("yafyaf_tui.__main__.YafyafApp") as app_class,
            patch("yafyaf_tui.__main__.new_yaf", return_value=0) as command,
            patch("yafyaf_tui.__main__.query_terminal") as query,
            patch("yafyaf_tui.__main__.TokenStore.default", return_value=TokenStore(Path(tmp) / "tokens.yaml")),
            patch("yafyaf_tui.__main__.load_config", return_value=Config()),
            self.assertRaises(SystemExit) as raised,
        ):
            main(["new", "--url", "http://localhost:3100", "--as", "sayings@example.com"])
        query.assert_not_called()
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(command.call_args.args[0], "http://localhost:3100")
        self.assertEqual(command.call_args.args[1].path.name, "tokens.yaml")
        self.assertEqual(command.call_args.kwargs, {"account": "sayings@example.com"})
        app_class.assert_not_called()


class NewYafTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TokenStore(Path(self.tmp.name) / "tokens.yaml")
        self.store.save(ME_ACCOUNT, "good")
        self.record = Path(self.tmp.name) / "draft-path"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, text: str, **create) -> tuple[int, str, str, Path | None]:
        """Run `yaf new` with an editor that writes text into the draft and records its path."""
        script = (
            "import pathlib, sys; "
            f"pathlib.Path({str(self.record)!r}).write_text(sys.argv[1]); "
            f"pathlib.Path(sys.argv[1]).write_text({text!r})"
        )
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.dict("os.environ", {"VISUAL": python_editor(script)}),
            patch("yafyaf_tui.api.client.YafyafClient.create_yaf", **create) as self.create_yaf,
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = new_yaf("http://localhost:3000", self.store, date(2026, 9, 14))
        draft = Path(self.record.read_text()) if self.record.exists() else None
        return code, out.getvalue(), err.getvalue(), draft

    def test_new_yaf_is_created_from_the_editor_unless_left_empty(self) -> None:
        saved = Yaf(id="y3", content="A new yaf", date=date(2026, 9, 14))
        code, out, _, draft = self._run("A new yaf\n", return_value=saved)
        self.assertEqual(code, 0)
        self.create_yaf.assert_called_once_with("A new yaf", date(2026, 9, 14))
        self.assertEqual(out.strip(), "Saved yaf for 2026-09-14.")
        self.assertRegex(draft.name, r"^yaf-new-\w+\.md$")
        self.assertFalse(draft.exists())

        # The editor starts from front matter holding the given day, and a changed date is used
        code, out, _, draft = self._run("---\ndate: 2026-09-13\n---\n\nYesterday\n", return_value=saved)
        self.create_yaf.assert_called_once_with("Yesterday", date(2026, 9, 13))
        self.assertEqual(out.strip(), "Saved yaf for 2026-09-13.")

        code, out, _, draft = self._run("---\ndate: 2026-09-14\n---\n\n")
        self.assertEqual(code, 0)
        self.create_yaf.assert_not_called()
        self.assertEqual(out.strip(), "Empty yaf, nothing saved.")
        self.assertFalse(draft.exists())

    def test_the_server_saying_is_printed_after_saving(self) -> None:
        def note_saying(*args):
            # What the real client does inside request
            client.saying = "There is always time."
            return Yaf(id="y3", content="A new yaf", date=date(2026, 9, 14))

        client = YafyafClient("http://localhost:3000", "good")
        with patch("yafyaf_tui.commands.YafyafClient", return_value=client):
            code, out, _, _ = self._run("A new yaf\n", side_effect=note_saying)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["Saved yaf for 2026-09-14.", "There is always time."])

    def test_failures_keep_the_draft_and_exit_with_an_error(self) -> None:
        code, _, err, draft = self._run("Lost?", side_effect=ApiConnectionError("Cannot reach it"))
        self.assertEqual(code, 1)
        self.assertIn(f"Cannot reach it\nYour yaf is kept in {draft}", err)
        self.assertEqual(draft.read_text(), "Lost?")
        draft.unlink()

        code, _, err, draft = self._run("---\ndate: soon\n---\nLost?")
        self.assertEqual(code, 1)
        self.create_yaf.assert_not_called()
        self.assertIn(f"An invalid date was entered\nYour yaf is kept in {draft}", err)
        draft.unlink()

        code, _, err, draft = self._run("Lost?", side_effect=AuthenticationError(401, "rejected"))
        self.assertEqual(code, 1)
        self.assertIn("Run yaf to log in again", err)
        self.assertTrue(draft.exists())
        self.assertEqual(self.store.token(self.store.current()), "")
        draft.unlink()

        # The rejected token was cleared, so the next run stops before opening the editor
        self.record.unlink()
        code, _, err, draft = self._run("Unused")
        self.assertEqual(code, 1)
        self.assertIn("Run yaf to log in first", err)
        self.assertIsNone(draft)

        self.store.save(ME_ACCOUNT, "good")
        err = io.StringIO()
        with patch.dict("os.environ", {"VISUAL": python_editor("raise SystemExit(3)")}), contextlib.redirect_stderr(err):
            self.assertEqual(new_yaf("http://localhost:3000", self.store), 1)
        self.assertIn("exited with status 3", err.getvalue())


class AppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TokenStore(Path(self.tmp.name) / "tokens.yaml")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _app(self, url: str = "http://localhost:3000") -> YafyafApp:
        return YafyafApp(url, Config(), self.store)

    def test_settings_screen_documents_every_binding(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            with patched_me(), patched_list():
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    await pilot.press("?")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, SettingsScreen)
                    keys = {static.content for static in app.screen.query(".shortcut-key")}
                    expected = {
                        shortcut.key
                        for section in shortcuts.SECTIONS
                        for shortcut in shortcuts.for_section(
                            section, YafsView.BINDINGS, YafsTable.BINDINGS, YafDetail.BINDINGS, app.BINDINGS
                        )
                    }
                    self.assertEqual(keys, expected)
                    self.assertTrue({"?", "q", "n", "e", "⇧+enter", "/", "r", "s", "y", "j", "k", "enter", "escape"} <= keys)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertNotIsInstance(app.screen, SettingsScreen)

                    # Clicking the account in the header is the other way in, and it must not take focus off the list
                    account = app.query_one("#app-account", AccountLink)
                    self.assertEqual(account.content, ME.email)
                    self.assertIs(account.parent, app.query_one("#app-header"))
                    await pilot.click("#app-account")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, SettingsScreen)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertTrue(app.query_one(YafsTable).has_focus)

        asyncio.run(exercise())

    def test_header_names_the_server_only_when_it_is_not_production(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            with patched_me(), patched_list():
                local = self._app("http://localhost:3000")
                async with local.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    self.assertEqual(local.query_one("#app-url", Static).content, "localhost:3000")

                production = self._app(DEFAULT_URL)
                async with production.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    self.assertFalse(production.query_one("#app-url").display)

        asyncio.run(exercise())

    def test_config_warnings_are_shown_as_notifications(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            config = Config(warnings=["Config file is not valid YAML: oops"])
            app = YafyafApp("http://localhost:3000", config, self.store)
            with patched_me(), patched_list():
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)
                    notification = app.screen.query_one(HeaderNotification)
                    self.assertEqual(header_message(app), config.warnings[0])
                    self.assertTrue(notification.has_class("-warning"))
                    # Shown in the header, between the title and the server URL, instead of as a toast
                    self.assertEqual(list(app.screen.query("Toast")), [])
                    header = app.query_one("#app-header")
                    self.assertIs(notification.parent, header)
                    self.assertGreater(notification.region.x, app.query_one("#app-title-group").region.right)
                    self.assertLess(notification.region.right, app.query_one("#app-url").region.x)

                    notification.clear_notification()
                    self.assertEqual(header_message(app), "")

        asyncio.run(exercise())

    def test_saved_token_is_checked_and_user_is_shown(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            with patched_me() as me, patched_list() as list_yafs:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    me.assert_called_once()
                    list_yafs.assert_called_once_with("", 1)
                    self.assertNotIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.user, ME)
                    self.assertFalse(app.query("#btn-sign-out"))  # it lives in Settings now
                    table = app.query_one(YafsTable)
                    self.assertEqual(table.row_count, 2)
                    self.assertEqual(row_text(table, 0), ["2026-09-13", "First yaf"])
                    date_cell = table.get_row_at(0)[0]
                    self.assertEqual(str(date_cell.style), load_palette("onedark")["comment"])
                    self.assertEqual(app.query_one("#yafs-status", Static).content, "2 yafs")
                    # The count shares the column header line, right-aligned
                    status = app.query_one("#yafs-status", Static)
                    self.assertEqual(status.region.y, app.query_one("#yafs-header-summary").region.y)
                    self.assertEqual(status.region.right, table.region.right)

        asyncio.run(exercise())

    def test_echo_shows_the_saying_and_score_from_the_last_response(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            app.animation_level = "none"  # No typewriter, so the text is there to read at once

            def list_with_headers(*args):
                # What the real client does inside request, on the worker thread
                app.client.saying = "There is always time."
                app.client.score = 94
                app.client.on_response()
                return ONE_PAGE

            with patched_me(), patch("yafyaf_tui.api.client.YafyafClient.list_yafs", side_effect=list_with_headers):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    saying = app.query_one(Echo)
                    score = app.query_one("#echo-score", Static)
                    self.assertEqual(saying.content, "There is always time.")
                    self.assertEqual(score.content, "94")
                    # The saying under the list, the score in the header just left of the account
                    self.assertGreater(saying.region.y, app.query_one(YafsTable).region.bottom - 1)
                    account = app.query_one("#app-account", AccountLink)
                    self.assertEqual(score.region.y, account.region.y)
                    self.assertEqual(score.region.right + 2, account.region.x)
                    self.assertEqual(account.region.right, app.query_one("#app-header").content_region.right)

        asyncio.run(exercise())

    def test_a_new_saying_is_erased_from_the_right_and_typed_from_the_left(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            with (
                patched_me(),
                patched_list(),
                patch("yafyaf_tui.widgets.echo.ERASE_SECONDS", 0.001),
                patch("yafyaf_tui.widgets.echo.TYPE_SECONDS", 0.001),
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    echo = app.query_one(Echo)
                    shown = []
                    with patch.object(echo, "update", side_effect=lambda text: shown.append(text)):
                        app.client.saying = "So it goes."
                        echo.sync()
                        await pilot.pause(0.3)
                        self.assertEqual(shown, ["S", "So", "So ", "So i", "So it", "So it ", "So it g", "So it go", "So it goe", "So it goes", "So it goes."])

                        # The old saying goes back to the common start, then the new one is typed out
                        shown.clear()
                        app.client.saying = "So be it."
                        echo.sync()
                        await pilot.pause(0.3)
                        self.assertEqual(shown[:9], ["So it goes", "So it goe", "So it go", "So it g", "So it ", "So it", "So i", "So ", "So b"])
                        self.assertEqual(shown[-1], "So be it.")

                        # The same saying again is left alone
                        shown.clear()
                        echo.sync()
                        await pilot.pause(0.1)
                        self.assertEqual(shown, [])

        asyncio.run(exercise())

    def test_echo_polls_for_a_new_saying_a_while_after_the_last_response(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            app.animation_level = "none"

            def me_with_headers():
                app.client.saying = "Keep it simple." if me.call_count == 1 else "You know better."
                app.client.score = 95
                app.client.on_response()
                return ME

            with (
                patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=me_with_headers) as me,
                patched_list(),
                patch("yafyaf_tui.widgets.echo.random.uniform", return_value=0.2) as uniform,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertEqual(me.call_count, 1)
                    uniform.assert_called_with(10.0, 30.0)
                    self.assertEqual(app.query_one(Echo).content, "Keep it simple.")

                    # Each poll's response arms the next one
                    await pilot.pause(0.5)
                    await settle(app, pilot)
                    self.assertGreaterEqual(me.call_count, 3)
                    self.assertEqual(app.query_one(Echo).content, "You know better.")
                    self.assertEqual(app.query_one("#echo-score", Static).content, "95")

                    # Signing out stops the polling
                    app.client.token = ""
                    app.query_one(Echo).sync()
                    polled = me.call_count
                    await pilot.pause(0.5)
                    await settle(app, pilot)
                    self.assertEqual(me.call_count, polled)

        asyncio.run(exercise())

    def test_login_saves_the_token_and_shows_the_user(self) -> None:
        async def exercise() -> None:
            app = self._app()
            session = Session(user=ME, token="fresh")
            with patch("yafyaf_tui.api.client.YafyafClient.login", return_value=session) as login, patched_list():
                async with app.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    self.assertIsInstance(app.screen, LoginScreen)

                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIs(app.screen.focused, app.screen.query_one("#password", Input))
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertEqual(
                        app.screen.query_one("#login-error", Static).content,
                        "Email and password are required",
                    )

                    app.screen.query_one("#email", Input).value = "me@example.com"
                    app.screen.query_one("#password", Input).value = "secret"
                    app.screen.query_one("#password", Input).focus()
                    await pilot.press("enter")
                    await settle(app, pilot)

                    login.assert_called_once_with("me@example.com", "secret")
                    self.assertNotIsInstance(app.screen, LoginScreen)
                    self.assertEqual(self.store.token(self.store.current()), "fresh")
                    self.assertEqual(app.client.token, "fresh")
                    self.assertEqual(app.user, ME)
                    self.assertEqual(app.query_one(YafsTable).row_count, 2)

        asyncio.run(exercise())

    def test_settings_signs_out_after_confirming_and_forgets_the_token(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            unreachable = ApiConnectionError("Cannot reach http://localhost:3000")
            logout = patch("yafyaf_tui.api.client.YafyafClient.logout", side_effect=unreachable)
            with patched_me(), patched_list(), logout as revoke:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    await pilot.press("?")
                    await pilot.pause()
                    self.assertEqual(app.screen.query_one("#account-selector", Select).value, ME_ACCOUNT)

                    await pilot.click("#btn-sign-out")
                    await settle(app, pilot)
                    # Settings closes first, so the confirmation is not stacked on top of it
                    self.assertIsInstance(app.screen, ConfirmDialog)
                    self.assertEqual(len(app.screen_stack), 2)
                    message = app.screen.query_one("#dialog-message", Static).content
                    self.assertEqual(message, "You are signed in as me@example.com (localhost:3000)")
                    await pilot.press("escape")
                    await settle(app, pilot)
                    revoke.assert_not_called()
                    self.assertEqual(self.store.token(self.store.current()), "good")
                    self.assertTrue(app.query_one(YafsTable).has_focus)

                    await pilot.press("?")
                    await pilot.pause()
                    await pilot.click("#btn-sign-out")
                    await settle(app, pilot)
                    await pilot.click("#confirm-btn")
                    await settle(app, pilot)
                    # The server could not revoke the token, but it is forgotten locally all the same
                    revoke.assert_called_once()
                    self.assertEqual(self.store.token(self.store.current()), "")
                    self.assertEqual(app.client.token, "")
                    self.assertIsNone(app.user)
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.query_one(YafsTable).row_count, 0)
                    self.assertEqual(app.query_one("#yafs-status", Static).content, "")

        asyncio.run(exercise())

    def test_an_unreachable_server_still_offers_sign_out_to_clear_the_token(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            unreachable = ApiConnectionError("Cannot reach http://localhost:3000")
            with patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=unreachable), \
                 patch("yafyaf_tui.api.client.YafyafClient.logout", side_effect=unreachable):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertIsNone(app.user)
                    await pilot.press("?")
                    await pilot.pause()
                    self.assertEqual(app.screen.query_one("#account-selector", Select).value, ME_ACCOUNT)

                    await pilot.click("#btn-sign-out")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmDialog)
                    message = app.screen.query_one("#dialog-message", Static).content
                    self.assertEqual(message, "You are signed in as me@example.com (localhost:3000)")
                    await pilot.click("#confirm-btn")
                    await settle(app, pilot)
                    self.assertEqual(self.store.accounts(), [])
                    self.assertIsInstance(app.screen, LoginScreen)

        asyncio.run(exercise())

    def test_an_unavailable_server_hides_the_list_until_a_retry_succeeds(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            answers = [NotFoundError(404, "Not Found"), ApiConnectionError("Cannot reach it: refused"), ME]
            with patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=answers), patched_list():
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertIsNone(app.user)
                    notice = app.query_one(OfflineNotice)
                    self.assertTrue(notice.display)
                    self.assertFalse(app.query_one(YafsView).display)
                    self.assertEqual(app.query_one("#offline-title", Static).content, "localhost:3000 is not available")
                    self.assertEqual(app.query_one("#offline-detail", Static).content, "The server answered 404: Not Found")
                    # The list's keys are gone with it; only the app's own keys remain
                    with patch.object(app, "_edit_yaf") as edit:
                        await pilot.press("n")
                        await pilot.pause()
                        edit.assert_not_called()
                    await pilot.press("?")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, SettingsScreen)
                    await pilot.press("escape")
                    await pilot.pause()

                    await pilot.press("r")
                    await settle(app, pilot)
                    self.assertTrue(notice.display)
                    self.assertEqual(app.query_one("#offline-detail", Static).content, "Cannot reach it: refused")

                    await pilot.click("#btn-retry")
                    await settle(app, pilot)
                    self.assertEqual(app.user, ME)
                    self.assertFalse(notice.display)
                    self.assertTrue(app.query_one(YafsView).display)
                    self.assertEqual(app.query_one(YafsTable).row_count, 2)
                    self.assertIs(app.focused, app.query_one(YafsTable))

        asyncio.run(exercise())

    def test_settings_switches_between_stored_accounts_and_adds_one(self) -> None:
        async def exercise() -> None:
            self.store.save(SAYINGS_ACCOUNT, "sayings-token")
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            app.animation_level = "none"
            users = {"good": ME, "sayings-token": SAYINGS, "fresh": OTHER}

            def me_for_token():
                app.client.score = {"good": 94, "sayings-token": 3, "fresh": 1}[app.client.token]
                app.client.on_response()
                return users[app.client.token]

            with (
                patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=me_for_token),
                patched_list() as list_yafs,
                patch("yafyaf_tui.api.client.YafyafClient.login", return_value=Session(user=OTHER, token="fresh")),
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertEqual(app.user, ME)
                    self.assertEqual(app.query_one("#app-account", Static).content, ME.email)
                    self.assertEqual(app.query_one("#echo-score", Static).content, "94")

                    await pilot.press("?")
                    await pilot.pause()
                    selector = app.screen.query_one("#account-selector", Select)
                    self.assertEqual(selector.value, ME_ACCOUNT)
                    self.assertEqual(
                        [label for label, _ in selector._options], [SAYINGS_ACCOUNT.label, ME_ACCOUNT.label, "Add account..."]
                    )

                    # Switching reloads the list as the other account, settings stays open
                    selector.value = SAYINGS_ACCOUNT
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, SettingsScreen)
                    self.assertEqual(app.user, SAYINGS)
                    self.assertEqual(app.client.token, "sayings-token")
                    self.assertEqual(self.store.current(), SAYINGS_ACCOUNT)
                    self.assertEqual(app.query_one("#app-account", Static).content, SAYINGS.email)
                    self.assertEqual(app.query_one("#echo-score", Static).content, "3")
                    self.assertEqual(list_yafs.call_count, 2)

                    # Adding an account closes settings and asks to log in; cancelling keeps the current one
                    selector.value = ADD_ACCOUNT
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.screen.query_one("#cancel-btn", Button).label, "Cancel")
                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertEqual(len(app.screen_stack), 1)
                    self.assertEqual((app.user, app.client.token), (SAYINGS, "sayings-token"))

                    await pilot.press("?")
                    await pilot.pause()
                    app.screen.query_one("#account-selector", Select).value = ADD_ACCOUNT
                    await settle(app, pilot)
                    app.screen.query_one("#email", Input).value = OTHER.email
                    app.screen.query_one("#password", Input).value = "secret"
                    app.screen.query_one("#password", Input).focus()
                    await pilot.press("enter")
                    await settle(app, pilot)
                    self.assertEqual(app.user, OTHER)
                    self.assertEqual(self.store.accounts(), [SAYINGS_ACCOUNT, ME_ACCOUNT, OTHER_ACCOUNT])
                    self.assertEqual(self.store.current(), OTHER_ACCOUNT)

                    # Signing out of one account falls back to another instead of asking to log in
                    with patch("yafyaf_tui.api.client.YafyafClient.logout"):
                        app.confirm_sign_out()
                        await pilot.pause()
                        await pilot.click("#confirm-btn")
                        await settle(app, pilot)
                    self.assertNotIsInstance(app.screen, LoginScreen)
                    self.assertEqual(self.store.accounts(), [SAYINGS_ACCOUNT, ME_ACCOUNT])
                    self.assertEqual(app.account, self.store.current())
                    self.assertEqual(app.user.email, app.account.email)

        asyncio.run(exercise())

    def test_s_cycles_through_the_stored_accounts(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            app.animation_level = "none"
            users = {"good": ME, "sayings-token": SAYINGS}
            with (
                patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=lambda: users[app.client.token]),
                patched_list() as list_yafs,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    # With one account there is nothing to cycle to
                    await pilot.press("s")
                    await settle(app, pilot)
                    self.assertEqual((app.user, header_message(app)), (ME, ""))

                    self.store.save(SAYINGS_ACCOUNT, "sayings-token")
                    self.store.select(ME_ACCOUNT)
                    for expected in (SAYINGS, ME, SAYINGS):
                        await pilot.press("s")
                        await settle(app, pilot)
                        self.assertEqual(app.user, expected)
                        self.assertEqual(self.store.current(), Account(URL, expected.email))
                        self.assertEqual(app.query_one("#app-account", Static).content, expected.email)
                        self.assertEqual(header_message(app), f"Switched to {Account(URL, expected.email).label}")
                    self.assertEqual(list_yafs.call_count, 4)

        asyncio.run(exercise())

    def test_accounts_on_other_servers_are_listed_and_switching_moves_the_client_there(self) -> None:
        async def exercise() -> None:
            production = Account(DEFAULT_URL, ME.email)
            self.store.save(production, "prod-token")
            self.store.save(ME_ACCOUNT, "good")
            config = Config(servers=[DEFAULT_URL, URL])
            app = YafyafApp(URL, config, self.store)
            app.animation_level = "none"
            users = {"good": ME, "prod-token": ME, "fresh": OTHER}
            with (
                patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=lambda: users[app.client.token]),
                patched_list() as list_yafs,
                patch("yafyaf_tui.api.client.YafyafClient.login", return_value=Session(user=OTHER, token="fresh")) as login,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertEqual((app.url, app.client.base_url), (URL, URL))
                    self.assertEqual(app.query_one("#app-url", Static).content, "localhost:3000")

                    # s moves to the production account: the client, header and server label follow
                    await pilot.press("s")
                    await settle(app, pilot)
                    self.assertEqual((app.account, app.client.base_url, app.client.token), (production, DEFAULT_URL, "prod-token"))
                    self.assertFalse(app.query_one("#app-url").display)
                    self.assertEqual(header_message(app), f"Switched to {ME.email}")
                    self.assertEqual(list_yafs.call_count, 2)

                    await pilot.press("?")
                    await pilot.pause()
                    selector = app.screen.query_one("#account-selector", Select)
                    self.assertEqual(
                        [label for label, _ in selector._options],
                        [ME.email, f"{ME.email} (localhost:3000)", "Add account..."],
                    )

                    # Adding an account asks which server, defaulting to the one in use
                    selector.value = ADD_ACCOUNT
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, LoginScreen)
                    server = app.screen.query_one("#login-server", Select)
                    self.assertEqual(server.value, DEFAULT_URL)
                    self.assertEqual([label for label, _ in server._options], ["yafyaf.com", "localhost:3000"])
                    server.value = URL
                    app.screen.query_one("#email", Input).value = OTHER.email
                    app.screen.query_one("#password", Input).value = "secret"
                    app.screen.query_one("#password", Input).focus()
                    await pilot.press("enter")
                    await settle(app, pilot)
                    login.assert_called_once_with(OTHER.email, "secret")
                    self.assertEqual((app.account, app.client.base_url), (OTHER_ACCOUNT, URL))
                    self.assertEqual(self.store.current(), OTHER_ACCOUNT)
                    self.assertEqual(app.query_one("#app-url", Static).content, "localhost:3000")

                # With one server there is no dropdown, just the server's name
                self.store.clear(production)
                self.store.clear(OTHER_ACCOUNT)
                self.store.clear(ME_ACCOUNT)
                app = YafyafApp(URL, Config(servers=[URL]), self.store)
                async with app.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertFalse(app.screen.query("#login-server"))
                    self.assertEqual(app.screen.query_one("#login-url", Static).content, URL)

        asyncio.run(exercise())

    def test_the_as_flag_picks_the_account_and_prefills_the_login_when_it_has_no_token(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            self.store.save(SAYINGS_ACCOUNT, "sayings-token")
            with patched_me() as me, patched_list():
                app = YafyafApp(URL, Config(), self.store, account=ME_ACCOUNT)
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    me.assert_called_once()
                    self.assertEqual(app.client.token, "good")

                app = YafyafApp(URL, Config(), self.store, login_email=OTHER.email)
                async with app.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.screen.query_one("#email", Input).value, OTHER.email)
                    self.assertIs(app.screen.focused, app.screen.query_one("#password", Input))

        asyncio.run(exercise())

    def test_rejected_token_falls_back_to_another_account_when_there_is_one(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            self.store.save(SAYINGS_ACCOUNT, "stale")
            app = self._app()
            error = AuthenticationError(401, "Authentication is required and has failed")

            def me_for_token():
                if app.client.token == "stale":
                    raise error
                return ME

            with patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=me_for_token), patched_list():
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)
                    self.assertNotIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.user, ME)
                    self.assertEqual(self.store.accounts(), [ME_ACCOUNT])
                    self.assertIn("rejected", header_message(app))

        asyncio.run(exercise())

    def test_rejected_token_is_cleared_and_login_is_asked_again(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "stale")
            app = self._app()
            error = AuthenticationError(401, "Authentication is required and has failed")
            with patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=error):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertEqual(self.store.token(self.store.current()), "")
                    self.assertIn("rejected", app.screen.query_one("#login-error", Static).content)

                    await pilot.press("escape")
                    await pilot.pause()
            self.assertEqual(app.return_code, 0)

        asyncio.run(exercise())


class YafsViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TokenStore(Path(self.tmp.name) / "tokens.yaml")
        self.store.save(ME_ACCOUNT, "good")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _app(self) -> YafyafApp:
        return YafyafApp("http://localhost:3000", Config(), self.store)

    def test_search_reloads_the_list_and_escape_returns_to_it(self) -> None:
        async def exercise() -> None:
            app = self._app()
            match = YafPage(yafs=YAFS[:1], records_count=1)
            with patched_me(), patched_list(ONE_PAGE, match) as list_yafs:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    view = app.query_one(YafsView)
                    search = view.query_one("#search", Input)

                    await pilot.press("slash")
                    self.assertTrue(search.has_focus)
                    await pilot.press("escape")
                    self.assertTrue(view.query_one(YafsTable).has_focus)
                    self.assertEqual(list_yafs.call_count, 1)

                    await pilot.press("slash", *"first", "enter")
                    await settle(app, pilot)
                    self.assertEqual(list_yafs.call_args_list[-1].args, ("first", 1))
                    self.assertTrue(view.query_one(YafsTable).has_focus)
                    self.assertEqual(view.query_one(YafsTable).row_count, 1)
                    self.assertEqual(view.query_one("#yafs-status", Static).content, "1 yaf matching 'first'")

                    # Submitting the same search again does not hit the API
                    await pilot.press("slash", "enter")
                    await settle(app, pilot)
                    self.assertEqual(list_yafs.call_count, 2)

        asyncio.run(exercise())

    def test_reaching_the_last_row_fetches_the_next_page(self) -> None:
        async def exercise() -> None:
            app = self._app()
            first = YafPage(yafs=YAFS, records_count=3, next_page={"page": 2, "sort": "date desc"})
            second = YafPage(yafs=(Yaf(id="y3", content="Third [link](http://x) [b]", date=date(2026, 9, 11)),), records_count=3)
            with patched_me(), patched_list(first, second) as list_yafs:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    view = app.query_one(YafsView)
                    self.assertEqual(view.query_one("#yafs-status", Static).content, "2 of 3 yafs")

                    await pilot.press("j")
                    await settle(app, pilot)
                    self.assertEqual(list_yafs.call_args_list[-1].args, ("", 2))
                    self.assertEqual(view.query_one(YafsTable).row_count, 3)
                    # A markdown link shows as its label, pointing at the URL; other brackets are not markup
                    summary = view.query_one(YafsTable).get_row_at(2)[1]
                    self.assertEqual(summary.plain, "Third link [b]")
                    link_span = next(span for span in summary.spans if span.style.link)
                    self.assertEqual(summary.plain[link_span.start : link_span.end], "link")
                    self.assertEqual((link_span.style.link, str(link_span.style.color.name)), ("http://x", "#61afef"))
                    self.assertEqual(view.query_one("#yafs-status", Static).content, "3 yafs")

                    await pilot.press("j")
                    await settle(app, pilot)
                    self.assertEqual(list_yafs.call_count, 2)

        asyncio.run(exercise())

    def _editor(self, change: str) -> tuple[str, Path]:
        """An editor that applies a change to the draft text and records the draft's path."""
        record = Path(self.tmp.name) / "draft-path"
        code = (
            "import pathlib, sys; draft = pathlib.Path(sys.argv[1]); "
            f"pathlib.Path({str(record)!r}).write_text(str(draft)); "
            f"text = draft.read_text(); draft.write_text({change})"
        )
        return python_editor(code), record

    def test_e_edits_the_yaf_and_saves_the_change(self) -> None:
        async def exercise() -> None:
            app = self._app()
            editor, record = self._editor("text.replace('Second', 'Changed').replace('09-12', '09-10') + '\\n'")
            on_server = Yaf(id="y2", content="Second yaf, edited on the web", date=date(2026, 9, 12))
            saved = Yaf(id="y2", content="Changed yaf, edited on the web", date=date(2026, 9, 10))
            update = patch("yafyaf_tui.api.client.YafyafClient.update_yaf", return_value=saved)
            with (
                patched_me(),
                patched_list() as list_yafs,
                patched_get(on_server) as get_yaf,
                patched_editor(editor),
                update as update_yaf,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    await pilot.press("j", "e")
                    await settle(app, pilot)

                    # The editor gets the server's copy, not the one the list loaded earlier
                    get_yaf.assert_called_once_with("y2")
                    update_yaf.assert_called_once_with("y2", "Changed yaf, edited on the web", date(2026, 9, 10))
                    draft = Path(record.read_text())
                    self.assertTrue(draft.name.startswith("yaf-y2-"))
                    self.assertFalse(draft.exists())
                    table = app.query_one(YafsTable)
                    self.assertTrue(table.has_focus)
                    self.assertEqual(table.cursor_row, 1)
                    self.assertEqual(row_text(table, 1), ["2026-09-10", "Changed yaf, edited on the web"])
                    self.assertEqual(app.query_one(YafsView).yafs[1], saved)
                    self.assertEqual(header_message(app), "Yaf updated")
                    list_yafs.assert_called_once()

        asyncio.run(exercise())

    def test_enter_shows_the_yaf_as_markdown_and_the_editor_returns_there(self) -> None:
        async def exercise() -> None:
            app = self._app()
            on_server = Yaf(id="y1", content="# Title\n\nSee [docs](https://d.com)\n\n- one\n- two", date=date(2026, 9, 13))
            saved = Yaf(id="y1", content="# Changed\n\nBody", date=date(2026, 9, 13))
            editor, record = self._editor("text.replace('Title', 'Changed')")
            blanked, _ = self._editor("'---\\ndate: 2026-09-13\\n---\\n'")
            after_delete = YafPage(yafs=YAFS[1:], records_count=1)
            with (
                patched_me(),
                patched_list(ONE_PAGE, after_delete) as list_yafs,
                patched_get(on_server) as get_yaf,
                patch("yafyaf_tui.api.client.YafyafClient.update_yaf", return_value=saved) as update_yaf,
                patch("yafyaf_tui.api.client.YafyafClient.delete_yaf") as delete_yaf,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    view = app.query_one(YafsView)
                    detail = app.query_one(YafDetail)
                    markdown = app.query_one(Markdown)
                    self.assertFalse(detail.display)

                    # Enter shows the server's copy, rendered, with the list's keys gone
                    await pilot.press("enter")
                    await settle(app, pilot)
                    get_yaf.assert_called_once_with("y1")
                    self.assertTrue(detail.display)
                    self.assertFalse(view.display)
                    self.assertEqual(app.query_one("#yaf-detail-date", Static).content, "Sunday, September 13, 2026")
                    # The date takes the saying's place at the bottom
                    self.assertFalse(app.query_one(Echo).display)
                    footer = app.query_one("#yaf-detail-footer")
                    self.assertGreater(footer.region.y, app.query_one("#yaf-detail-scroll").region.bottom - 1)
                    yaf_id = app.query_one("#yaf-detail-id", Static)
                    self.assertEqual(yaf_id.content, "y1")
                    self.assertEqual(yaf_id.region.right, footer.content_region.right)
                    self.assertEqual([(level, text) for level, text, _ in markdown.table_of_contents], [(1, "Title")])
                    self.assertEqual(len(markdown.query("MarkdownBulletList")), 1)
                    self.assertIs(app.focused, app.query_one("#yaf-detail-scroll"))
                    # A link is a terminal hyperlink as well as a click for the app, like in the list
                    paragraph = markdown.query_one("MarkdownParagraph")
                    link = next(span for span in paragraph._content.spans if not isinstance(span.style, str))
                    self.assertEqual((paragraph._content.plain[link.start : link.end], link.style.link), ("docs", "https://d.com"))
                    with patch.object(app, "open_url") as open_url:
                        await pilot.click(paragraph, offset=(5, 0))
                        await pilot.pause()
                    open_url.assert_called_once_with("https://d.com")

                    # y copies the whole yaf, or just the text selected with the mouse
                    with patch.object(app, "copy_to_clipboard") as copy:
                        await pilot.press("y")
                        await pilot.pause()
                        copy.assert_called_once_with(on_server.content)
                        self.assertEqual(header_message(app), "Yaf copied")
                        await pilot.mouse_down(paragraph, offset=(0, 0))
                        await pilot.hover(paragraph, offset=(3, 0))
                        await pilot.mouse_up(paragraph, offset=(3, 0))
                        await pilot.pause()
                        copy.reset_mock()
                        await pilot.press("y")
                        await pilot.pause()
                        copy.assert_called_once_with("See ")
                        self.assertEqual(header_message(app), "Selection copied")
                    with patch.object(app, "_edit_yaf") as edit:
                        await pilot.press("n")
                        await pilot.pause()
                        edit.assert_not_called()

                    for back in ("escape", "q"):
                        await pilot.press(back)
                        await pilot.pause()
                        self.assertFalse(detail.display)
                        self.assertTrue(view.display)
                        self.assertTrue(app.query_one(Echo).display)
                        self.assertTrue(app.query_one(YafsTable).has_focus)
                        self.assertFalse(app._exit)
                        await pilot.press("enter")
                        await settle(app, pilot)
                        self.assertTrue(detail.display)

                    # Editing from the view comes back to the view, with the saved content
                    with patched_editor(editor):
                        await pilot.press("e")
                        await settle(app, pilot)
                    update_yaf.assert_called_once()
                    self.assertFalse(Path(record.read_text()).exists())
                    self.assertTrue(detail.display)
                    self.assertEqual([(level, text) for level, text, _ in markdown.table_of_contents], [(1, "Changed")])
                    self.assertEqual(row_text(app.query_one(YafsTable), 0), ["2026-09-13", "Changed"])
                    self.assertEqual(header_message(app), "Yaf updated")

                    # Blanking it from the view deletes it, and there is nothing left to view
                    with patched_editor(blanked):
                        await pilot.press("e")
                        await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmDialog)
                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertTrue(detail.display)
                    with patched_editor(blanked):
                        await pilot.press("e")
                        await settle(app, pilot)
                    await pilot.click("#confirm-btn")
                    await settle(app, pilot)
                    delete_yaf.assert_called_once_with("y1")
                    self.assertFalse(detail.display)
                    self.assertTrue(view.display)
                    self.assertEqual(list_yafs.call_count, 2)
                    self.assertTrue(app.query_one(YafsTable).has_focus)

                    # Shift+Enter in the list goes straight to the editor, in terminals that can send it
                    editor, record = self._editor("text + '\\n'")
                    with patched_editor(editor):
                        await pilot.press("shift+enter")
                        await settle(app, pilot)
                    self.assertTrue(Path(record.read_text()).name.startswith("yaf-y2-"))
                    self.assertFalse(detail.display)

        asyncio.run(exercise())

    def test_y_copies_the_highlighted_yaf_from_the_list(self) -> None:
        async def exercise() -> None:
            app = self._app()
            with patched_me(), patched_list():
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    with patch.object(app, "copy_to_clipboard") as copy:
                        await pilot.press("j", "y")
                        await pilot.pause()
                    copy.assert_called_once_with(YAFS[1].content)
                    self.assertEqual(header_message(app), "Yaf copied")

        asyncio.run(exercise())

    def test_nothing_is_saved_without_a_change_and_a_failed_save_keeps_the_draft(self) -> None:
        async def exercise() -> None:
            app = self._app()
            error = ApiError(422, "content is too long")
            update = patch("yafyaf_tui.api.client.YafyafClient.update_yaf", side_effect=error)
            with patched_me(), patched_list(), patched_get(), update as update_yaf:
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)

                    # Saving an untouched file only adds the final newline, which is not an edit
                    editor, record = self._editor("text + '\\n'")
                    with patched_editor(editor):
                        await pilot.press("e")
                        await settle(app, pilot)
                    update_yaf.assert_not_called()
                    self.assertFalse(Path(record.read_text()).exists())
                    self.assertEqual(header_message(app), "")

                    with patched_editor(python_editor("raise SystemExit(3)")) as resumed:
                        await pilot.press("e")
                        await settle(app, pilot)
                    update_yaf.assert_not_called()
                    self.assertEqual(resumed, [True])
                    self.assertIn("exited with status 3", header_message(app))

                    # A bad draft opens a dialog that has to be answered; Discard throws the edit away
                    editor, record = self._editor("text.replace('2026-09-13', '2026-02-30')")
                    with patched_editor(editor):
                        await pilot.press("e")
                        await settle(app, pilot)
                    update_yaf.assert_not_called()
                    draft = Path(record.read_text())
                    self.assertIsInstance(app.screen, NotSavedDialog)
                    self.assertEqual(app.screen.query_one("#dialog-message", Static).content, "An invalid date was entered")
                    self.assertEqual(app.screen.query_one("#dialog-title", Static).content, "Error saving the Yaf")
                    self.assertFalse(app.screen.query("#retry-btn"))  # Sending the same text again cannot help
                    self.assertIs(app.screen.focused, app.screen.query_one("#edit-btn"))
                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, NotSavedDialog)
                    self.assertTrue(draft.read_text().startswith("---\ndate: 2026-02-30\n---"))
                    await pilot.click("#confirm-btn")
                    await settle(app, pilot)
                    self.assertNotIsInstance(app.screen, NotSavedDialog)
                    self.assertFalse(draft.exists())

                    # Edit again reopens the same draft; a server error then offers a retry
                    with patched_editor(editor):
                        await pilot.press("e")
                        await settle(app, pilot)
                    draft = Path(record.read_text())
                    fixing, record = self._editor("text.replace('2026-02-30', '2026-09-12').replace('First', 'Fixed')")
                    with patched_editor(fixing):
                        await pilot.click("#edit-btn")
                        await settle(app, pilot)
                    self.assertEqual(Path(record.read_text()), draft)
                    update_yaf.assert_called_once_with("y1", "Fixed yaf\nwith a second line", date(2026, 9, 12))
                    self.assertIsInstance(app.screen, NotSavedDialog)
                    self.assertEqual(app.screen.query_one("#dialog-message", Static).content, "content is too long")
                    self.assertTrue(draft.exists())

                    saved = Yaf(id="y1", content="Fixed yaf\nwith a second line", date=date(2026, 9, 12))
                    update_yaf.side_effect = None
                    update_yaf.return_value = saved
                    await pilot.click("#retry-btn")
                    await settle(app, pilot)
                    self.assertEqual(update_yaf.call_count, 2)
                    self.assertNotIsInstance(app.screen, NotSavedDialog)
                    self.assertFalse(draft.exists())
                    self.assertEqual(header_message(app), "Yaf updated")
                    self.assertEqual(row_text(app.query_one(YafsTable), 0), ["2026-09-12", "Fixed yaf"])

        asyncio.run(exercise())

    def test_new_yaf_key_and_button_write_a_new_yaf_in_the_editor(self) -> None:
        async def exercise() -> None:
            app = self._app()
            written = self._editor("'---\\ndate: 2026-09-10\\n---\\n\\nFresh yaf\\n'")
            # Changing only the date of an empty draft still counts as a cancel
            left_empty = self._editor("'---\\ndate: 2026-09-09\\n---\\n\\n'")
            created = Yaf(id="y9", content="Fresh yaf", date=date(2026, 9, 10))
            create = patch("yafyaf_tui.api.client.YafyafClient.create_yaf", return_value=created)
            with patched_me(), patched_list() as list_yafs, create as create_yaf:
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)

                    editor, record = written
                    with patched_editor(editor):
                        await pilot.press("n")
                        await settle(app, pilot)
                    draft = Path(record.read_text())
                    self.assertTrue(draft.name.startswith("yaf-new-"))
                    self.assertFalse(draft.exists())
                    create_yaf.assert_called_once_with("Fresh yaf", date(2026, 9, 10))
                    self.assertEqual(list_yafs.call_count, 2)
                    self.assertEqual(header_message(app), "Yaf created")

                    editor, record = left_empty
                    record.unlink()
                    with patched_editor(editor):
                        await pilot.click("#btn-new-yaf")
                        await settle(app, pilot)
                    self.assertFalse(Path(record.read_text()).exists())
                    create_yaf.assert_called_once()
                    self.assertEqual(header_message(app), "Yaf created")
                    self.assertTrue(app.query_one(YafsTable).has_focus)

        asyncio.run(exercise())

    def test_a_yaf_deleted_elsewhere_refreshes_the_list_or_is_saved_as_a_new_yaf(self) -> None:
        async def exercise() -> None:
            app = self._app()
            after_delete = YafPage(yafs=YAFS[1:], records_count=1)
            deleted = NotFoundError(404, "Record not found")
            editor, record = self._editor("text.replace('Second', 'Rescued')")
            created = Yaf(id="y9", content="Rescued yaf", date=date(2026, 9, 12))
            with (
                patched_me(),
                patched_list(ONE_PAGE, after_delete, ONE_PAGE) as list_yafs,
                patched_editor(editor),
                patch("yafyaf_tui.api.client.YafyafClient.update_yaf", side_effect=deleted) as update_yaf,
                patch("yafyaf_tui.api.client.YafyafClient.create_yaf", return_value=created) as create_yaf,
            ):
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)

                    # Deleted before opening: no editor, and the list reloads without it
                    with patched_get(error=deleted):
                        await pilot.press("e")
                        await settle(app, pilot)
                    self.assertFalse(record.exists())
                    self.assertEqual(list_yafs.call_count, 2)
                    self.assertEqual(row_text(app.query_one(YafsTable), 0), ["2026-09-12", "Second yaf"])
                    self.assertIn("deleted", header_message(app))

                    # Deleted while the editor was open: the edit becomes a new yaf
                    with patched_get():
                        await pilot.press("e")
                        await settle(app, pilot)
                    update_yaf.assert_called_once_with("y2", "Rescued yaf", date(2026, 9, 12))
                    create_yaf.assert_called_once_with("Rescued yaf", date(2026, 9, 12))
                    self.assertFalse(Path(record.read_text()).exists())
                    self.assertEqual(list_yafs.call_count, 3)
                    self.assertIn("saved your edit as a new yaf", header_message(app))

        asyncio.run(exercise())

    def test_blanking_a_yaf_deletes_it_after_confirmation(self) -> None:
        async def exercise() -> None:
            app = self._app()
            # Whitespace under the front matter is as blank as an empty file
            editor, record = self._editor("'---\\ndate: 2026-09-13\\n---\\n  \\n'")
            after_delete = YafPage(yafs=YAFS[1:], records_count=1)
            with (
                patched_me(),
                patched_list(ONE_PAGE, after_delete, after_delete) as list_yafs,
                patched_get(),
                patched_editor(editor),
                patch("yafyaf_tui.api.client.YafyafClient.update_yaf") as update_yaf,
                patch("yafyaf_tui.api.client.YafyafClient.delete_yaf") as delete_yaf,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)

                    # Enter lands on Cancel, so a reflexive Enter does not delete
                    await pilot.press("e")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmDialog)
                    self.assertEqual(app.screen.query_one("#dialog-message", Static).content, "Delete the yaf from 2026-09-13?")
                    self.assertEqual(app.screen.query_one("#dialog-detail", Static).content, "First yaf")
                    self.assertFalse(Path(record.read_text()).exists())
                    await pilot.press("enter")
                    await settle(app, pilot)
                    self.assertNotIsInstance(app.screen, ConfirmDialog)
                    delete_yaf.assert_not_called()

                    await pilot.press("e")
                    await settle(app, pilot)
                    await pilot.press("escape")
                    await settle(app, pilot)
                    delete_yaf.assert_not_called()

                    await pilot.press("e")
                    await settle(app, pilot)
                    await pilot.click("#confirm-btn")
                    await settle(app, pilot)
                    delete_yaf.assert_called_once_with("y1")
                    update_yaf.assert_not_called()
                    self.assertEqual(list_yafs.call_count, 2)
                    self.assertEqual(row_text(app.query_one(YafsTable), 0), ["2026-09-12", "Second yaf"])
                    self.assertEqual(header_message(app), "Yaf deleted")

                    # Already deleted elsewhere counts as deleted; other failures are reported
                    for failure, message in (
                        (NotFoundError(404, "Record not found"), "Yaf deleted"),
                        (ApiConnectionError("Cannot reach it"), "Not deleted: Cannot reach it"),
                    ):
                        delete_yaf.side_effect = failure
                        await pilot.press("e")
                        await settle(app, pilot)
                        await pilot.click("#confirm-btn")
                        await settle(app, pilot)
                        self.assertEqual(header_message(app), message)
                    self.assertEqual(list_yafs.call_count, 3)

        asyncio.run(exercise())

    def test_the_highlight_follows_the_mouse_and_a_click_opens_the_row(self) -> None:
        async def exercise() -> None:
            app = self._app()
            linked = Yaf(id="y3", content="[docs](https://d.com)", date=date(2026, 9, 1))
            page = YafPage(yafs=(*YAFS, linked), records_count=3)
            with patched_me(), patched_list(page), patched_get(linked) as get_yaf:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    table = app.query_one(YafsTable)
                    await pilot.hover(table, offset=(20, 1))
                    await pilot.pause()
                    self.assertEqual(table.cursor_row, 1)
                    await pilot.hover(table, offset=(2, 0))
                    await pilot.pause()
                    self.assertEqual(table.cursor_row, 0)

                    # Over a link, the row is highlighted too
                    link_x = DATE_WIDTH + 3 * table.cell_padding
                    await pilot.hover(table, offset=(link_x, 2))
                    await pilot.pause()
                    self.assertEqual(table.cursor_row, 2)
                    self.assertTrue(any(span.style.underline for span in table.get_row_at(2)[1].spans))
                    await pilot.hover(table, offset=(2, 0))
                    await pilot.pause()

                    await pilot.click(table, offset=(20, 1))
                    await settle(app, pilot)
                    get_yaf.assert_called_once_with("y2")
                    self.assertTrue(app.query_one(YafDetail).display)

        asyncio.run(exercise())

    def test_links_are_blue_underlined_on_hover_and_open_on_click(self) -> None:
        text = summary_text("See [ESI](https://e.com/a?b=1&c=2) and https://x.tv/p, or (https://ooh.directory).", "#61afef")
        self.assertEqual(text.plain, "See ESI and https://x.tv/p, or (https://ooh.directory).")
        links = [(text.plain[span.start : span.end], span.style.link) for span in text.spans]
        self.assertEqual(
            links,
            [
                ("ESI", "https://e.com/a?b=1&c=2"),
                ("https://x.tv/p", "https://x.tv/p"),
                ("https://ooh.directory", "https://ooh.directory"),
            ],
        )
        self.assertTrue(all(span.style.color.name == "#61afef" and not span.style.underline for span in text.spans))
        hovered = summary_text("[a](https://a.com) [b](https://b.com)", hovered_link="https://b.com")
        self.assertEqual([span.style.underline for span in hovered.spans], [False, True])

        # A markdown heading drops its marks and turns the heading color; links inside stay links
        for summary in ("# Portland Trophy Cup", "### Portland Trophy Cup ##"):
            heading = summary_text(summary, heading_color="#e5c07b")
            self.assertEqual((heading.plain, str(heading.style)), ("Portland Trophy Cup", "#e5c07b"))
        heading = summary_text("## See [docs](https://d.com)", "#61afef", heading_color="#e5c07b")
        self.assertEqual((heading.plain, heading.spans[0].style.link), ("See docs", "https://d.com"))
        for not_heading in ("#hashtag", "C# notes", "#"):
            self.assertEqual(summary_text(not_heading, heading_color="#e5c07b").plain, not_heading)

        async def exercise() -> None:
            app = self._app()
            page = YafPage(yafs=(Yaf(id="y1", content="Read [docs](https://d.com) now", date=date(2026, 9, 13)),), records_count=1)
            with (
                patched_me(),
                patched_list(page),
                patched_get() as get_yaf,
                patch.object(YafyafApp, "open_url") as open_url,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    table = app.query_one(YafsTable)
                    # Summary cells start after the padded date column and their own left padding
                    link_x = DATE_WIDTH + 2 * table.cell_padding + table.cell_padding + len("Read ")

                    def link_underlined() -> bool:
                        return any(span.style.underline for span in table.get_row_at(0)[1].spans)

                    await pilot.hover(table, offset=(link_x, 0))
                    await pilot.pause()
                    self.assertTrue(link_underlined())
                    await pilot.hover(table, offset=(link_x - 3, 0))
                    await pilot.pause()
                    self.assertFalse(link_underlined())

                    await pilot.click(table, offset=(link_x + 1, 0))
                    await settle(app, pilot)
                    open_url.assert_called_once_with("https://d.com")
                    get_yaf.assert_not_called()

                    # Outside the link, a click opens the yaf
                    with patched_editor(python_editor("pass")):
                        await pilot.click(table, offset=(link_x - 3, 0))
                        await settle(app, pilot)
                    get_yaf.assert_called_once_with("y1")

        asyncio.run(exercise())

    def test_api_failure_is_reported_in_the_status_line(self) -> None:
        async def exercise() -> None:
            app = self._app()
            error = ApiConnectionError("Cannot reach http://localhost:3000: refused")
            with patched_me(), patch("yafyaf_tui.api.client.YafyafClient.list_yafs", side_effect=error):
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)
                    self.assertEqual(app.query_one("#yafs-status", Static).content, str(error))
                    self.assertEqual(app.query_one(YafsTable).row_count, 0)

        asyncio.run(exercise())
