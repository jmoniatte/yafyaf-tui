import asyncio
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input, Static

from yafyaf_tui import __version__, shortcuts
from yafyaf_tui.__main__ import main
from yafyaf_tui.api import AuthenticationError, Session, User
from yafyaf_tui.app import YafyafApp
from yafyaf_tui.config import DEFAULT_URL, Config, TokenStore
from yafyaf_tui.screens import HelpScreen, LoginScreen

ME = User(id="abc", email="me@example.com")


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
            with patch("yafyaf_tui.api.client.YafyafClient.me", return_value=ME):
                async with app.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    await pilot.press("?")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, HelpScreen)
                    keys = {static.content for static in app.screen.query(".shortcut-key")}
                    expected = {
                        shortcut.key
                        for section in shortcuts.SECTIONS
                        for shortcut in shortcuts.for_section(section, app.BINDINGS)
                    }
                    self.assertEqual(keys, expected)
                    self.assertIn("?", keys)
                    self.assertIn("q", keys)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertNotIsInstance(app.screen, HelpScreen)

        asyncio.run(exercise())

    def test_header_names_the_server_only_when_it_is_not_production(self) -> None:
        async def exercise() -> None:
            self.store.save("good")
            with patch("yafyaf_tui.api.client.YafyafClient.me", return_value=ME):
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
            with patch("yafyaf_tui.api.client.YafyafClient.me", return_value=ME):
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await pilot.pause()
                    messages = [toast.message for toast in app._notifications]
                    self.assertEqual(messages, config.warnings)

        asyncio.run(exercise())

    def test_saved_token_is_checked_and_user_is_shown(self) -> None:
        async def exercise() -> None:
            self.store.save("good")
            app = self._app()
            with patch("yafyaf_tui.api.client.YafyafClient.me", return_value=ME) as me:
                async with app.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    await app.workers.wait_for_complete()
                    await pilot.pause()
                    me.assert_called_once()
                    self.assertNotIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.query_one("#main-placeholder", Static).content, "Signed in as me@example.com")

        asyncio.run(exercise())

    def test_login_saves_the_token_and_shows_the_user(self) -> None:
        async def exercise() -> None:
            app = self._app()
            session = Session(user=ME, token="fresh")
            with patch("yafyaf_tui.api.client.YafyafClient.login", return_value=session) as login:
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
                    await app.screen.workers.wait_for_complete()
                    await pilot.pause()

                    login.assert_called_once_with("me@example.com", "secret")
                    self.assertNotIsInstance(app.screen, LoginScreen)
                    self.assertEqual(self.store.load(), "fresh")
                    self.assertEqual(app.client.token, "fresh")
                    self.assertEqual(app.query_one("#main-placeholder", Static).content, "Signed in as me@example.com")

        asyncio.run(exercise())

    def test_rejected_token_is_cleared_and_login_is_asked_again(self) -> None:
        async def exercise() -> None:
            self.store.save("stale")
            app = self._app()
            error = AuthenticationError(401, "Authentication is required and has failed")
            with patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=error):
                async with app.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    await app.workers.wait_for_complete()
                    await pilot.pause()
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertEqual(self.store.load(), "")
                    self.assertIn("rejected", app.screen.query_one("#login-error", Static).content)

                    await pilot.press("escape")
                    await pilot.pause()
            self.assertEqual(app.return_code, 0)

        asyncio.run(exercise())
