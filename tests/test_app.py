import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Static

from yafyaf_tui import shortcuts
from yafyaf_tui.accounts import TokenStore
from yafyaf_tui.app import YafyafApp
from yafyaf_tui.config import DEFAULT_URL, Config
from yafyaf_tui.screens import SettingsScreen
from yafyaf_tui.widgets import AccountLink, Echo, HeaderNotification, YafDetail, YafsTable, YafsView

from support import ME, ME_ACCOUNT, ONE_PAGE, header_message, patched_list, patched_me, settle

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

