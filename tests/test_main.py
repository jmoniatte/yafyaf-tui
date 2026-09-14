import asyncio
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from datetime import date

from textual.widgets import Input, Static

from yafyaf_tui import __version__, shortcuts
from yafyaf_tui.__main__ import main
from yafyaf_tui.api import ApiConnectionError, AuthenticationError, Session, User, Yaf, YafPage
from yafyaf_tui.app import YafyafApp
from yafyaf_tui.config import DEFAULT_URL, Config, TokenStore
from yafyaf_tui.screens import HelpScreen, LoginScreen, YafDetailScreen
from yafyaf_tui.widgets import YafsTable, YafsView

ME = User(id="abc", email="me@example.com")
YAFS = (
    Yaf(id="y1", content="First yaf\nwith a second line", date=date(2026, 9, 13)),
    Yaf(id="y2", content="Second yaf", date=date(2026, 9, 12)),
)
ONE_PAGE = YafPage(yafs=YAFS, records_count=2)


def patched_me():
    return patch("yafyaf_tui.api.client.YafyafClient.me", return_value=ME)


def patched_list(*pages: YafPage):
    if not pages:
        return patch("yafyaf_tui.api.client.YafyafClient.list_yafs", return_value=ONE_PAGE)
    return patch("yafyaf_tui.api.client.YafyafClient.list_yafs", side_effect=list(pages))


async def settle(app: YafyafApp, pilot) -> None:
    """Let every worker on every screen finish, then let the UI catch up."""
    await pilot.pause()
    await app.workers.wait_for_complete()
    for screen in app.screen_stack:
        await screen.workers.wait_for_complete()
    await pilot.pause()


class MainTest(unittest.TestCase):
    def test_version_flag_exits_without_starting_the_tui(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"YafYaf TUI {__version__}")

    def test_url_flag_and_environment_pick_the_server(self) -> None:
        with patch("yafyaf_tui.__main__.YafyafApp") as app_class:
            with patch.dict("os.environ", {"YAFYAF_URL": ""}):
                main([])
            with patch.dict("os.environ", {"YAFYAF_URL": "http://localhost:3000"}):
                main([])
                main(["--url", "http://localhost:3100/"])
        urls = [call.kwargs["url"] for call in app_class.call_args_list]
        self.assertEqual(urls, [DEFAULT_URL, "http://localhost:3000", "http://localhost:3100"])
        self.assertEqual(app_class.return_value.run.call_count, 3)


class AppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TokenStore(Path(self.tmp.name) / "token")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _app(self, url: str = "http://localhost:3000") -> YafyafApp:
        return YafyafApp(url, Config(), self.store)

    def test_help_screen_documents_every_binding(self) -> None:
        async def exercise() -> None:
            self.store.save("good")
            app = self._app()
            with patched_me(), patched_list():
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    await pilot.press("?")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, HelpScreen)
                    keys = {static.content for static in app.screen.query(".shortcut-key")}
                    expected = {
                        shortcut.key
                        for section in shortcuts.SECTIONS
                        for shortcut in shortcuts.for_section(
                            section, YafsView.BINDINGS, YafsTable.BINDINGS, YafDetailScreen.BINDINGS, app.BINDINGS
                        )
                    }
                    self.assertEqual(keys, expected)
                    self.assertTrue({"?", "q", "/", "r", "j", "k", "enter", "escape"} <= keys)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertNotIsInstance(app.screen, HelpScreen)

        asyncio.run(exercise())

    def test_header_names_the_server_only_when_it_is_not_production(self) -> None:
        async def exercise() -> None:
            self.store.save("good")
            with patched_me(), patched_list():
                local = self._app("http://localhost:3000")
                async with local.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    self.assertEqual(local.query_one("#app-url", Static).content, "http://localhost:3000")

                production = self._app(DEFAULT_URL)
                async with production.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    self.assertFalse(production.query("#app-url"))

        asyncio.run(exercise())

    def test_config_warnings_are_shown_as_notifications(self) -> None:
        async def exercise() -> None:
            self.store.save("good")
            config = Config(warnings=["Config file is not valid YAML: oops"])
            app = YafyafApp("http://localhost:3000", config, self.store)
            with patched_me(), patched_list():
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)
                    messages = [toast.message for toast in app._notifications]
                    self.assertEqual(messages, config.warnings)

        asyncio.run(exercise())

    def test_saved_token_is_checked_and_user_is_shown(self) -> None:
        async def exercise() -> None:
            self.store.save("good")
            app = self._app()
            with patched_me() as me, patched_list() as list_yafs:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    me.assert_called_once()
                    list_yafs.assert_called_once_with("", 1)
                    self.assertNotIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.query_one("#status-line", Static).content, "Signed in as me@example.com")
                    table = app.query_one(YafsTable)
                    self.assertEqual(table.row_count, 2)
                    self.assertEqual(table.get_row_at(0), ["2026-09-13", "First yaf"])
                    self.assertEqual(app.query_one("#yafs-status", Static).content, "2 yafs")

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
                    self.assertEqual(self.store.load(), "fresh")
                    self.assertEqual(app.client.token, "fresh")
                    self.assertEqual(app.query_one("#status-line", Static).content, "Signed in as me@example.com")
                    self.assertEqual(app.query_one(YafsTable).row_count, 2)

        asyncio.run(exercise())

    def test_rejected_token_is_cleared_and_login_is_asked_again(self) -> None:
        async def exercise() -> None:
            self.store.save("stale")
            app = self._app()
            error = AuthenticationError(401, "Authentication is required and has failed")
            with patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=error):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertEqual(self.store.load(), "")
                    self.assertIn("rejected", app.screen.query_one("#login-error", Static).content)

                    await pilot.press("escape")
                    await pilot.pause()
            self.assertEqual(app.return_code, 0)

        asyncio.run(exercise())


class YafsViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TokenStore(Path(self.tmp.name) / "token")
        self.store.save("good")

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
            second = YafPage(yafs=(Yaf(id="y3", content="Third", date=date(2026, 9, 11)),), records_count=3)
            with patched_me(), patched_list(first, second) as list_yafs:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    view = app.query_one(YafsView)
                    self.assertEqual(view.query_one("#yafs-status", Static).content, "2 of 3 yafs")

                    await pilot.press("j")
                    await settle(app, pilot)
                    self.assertEqual(list_yafs.call_args_list[-1].args, ("", 2))
                    self.assertEqual(view.query_one(YafsTable).row_count, 3)
                    self.assertEqual(view.query_one("#yafs-status", Static).content, "3 yafs")

                    await pilot.press("j")
                    await settle(app, pilot)
                    self.assertEqual(list_yafs.call_count, 2)

        asyncio.run(exercise())

    def test_enter_opens_the_yaf_and_escape_comes_back(self) -> None:
        async def exercise() -> None:
            app = self._app()
            with patched_me(), patched_list():
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    await pilot.press("j", "enter")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, YafDetailScreen)
                    self.assertEqual(app.screen.yaf, YAFS[1])
                    self.assertEqual(app.screen.query_one("#yaf-detail-date", Static).content, "2026-09-12")
                    self.assertIn("Second yaf", str(app.screen.query_one("#yaf-detail-content").source))

                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertNotIsInstance(app.screen, YafDetailScreen)
                    self.assertTrue(app.query_one(YafsTable).has_focus)

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
