import asyncio
import contextlib
import io
import unittest

from textual.widgets import Static

from yafyaf_tui import __version__, shortcuts
from yafyaf_tui.__main__ import main
from yafyaf_tui.app import YafyafApp
from yafyaf_tui.config import Config
from yafyaf_tui.screens import HelpScreen


class MainTest(unittest.TestCase):
    def test_version_flag_exits_without_starting_the_tui(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"YafYaf TUI {__version__}")


class AppTest(unittest.TestCase):
    def test_help_screen_documents_every_binding(self) -> None:
        async def exercise() -> None:
            app = YafyafApp(Config(url="http://localhost:3000", token="abc"))
            async with app.run_test(size=(100, 34)) as pilot:
                await pilot.pause()
                self.assertEqual(
                    app.query_one("#main-placeholder", Static).content,
                    "Connected to http://localhost:3000",
                )
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

    def test_shows_config_help_when_settings_are_missing(self) -> None:
        async def exercise() -> None:
            config = Config(warnings=["Config file not found: /x/config.yaml"])
            app = YafyafApp(config)
            async with app.run_test(size=(100, 34)) as pilot:
                await pilot.pause()
                app.query_one("#no-config-dialog")
                warnings = [static.content for static in app.query(".no-config-warning")]
                self.assertEqual(warnings, config.warnings)
                self.assertFalse(app.query("#main-placeholder"))

        asyncio.run(exercise())
