import asyncio
import re
import tempfile
import unittest
from pathlib import Path

from tui_kit.theme import list_themes, load_palette

from yafyaf_tui.accounts import TokenStore
from yafyaf_tui.app import YafyafApp, load_stylesheet
from yafyaf_tui.config import Config
from yafyaf_tui.widgets import YafsTable

from support import ME_ACCOUNT, no_server, patched_list, patched_me


class ThemeTest(unittest.TestCase):
    def test_every_theme_fills_each_variable_the_stylesheets_use(self):
        required = set(re.findall(r"\$([\w-]+)", load_stylesheet()))
        self.assertIn("bg-dark", required)
        for name in list_themes():
            with self.subTest(theme=name):
                self.assertEqual(required - set(load_palette(name)), set())

    def test_apply_theme_swaps_variables(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = TokenStore(Path(tmp.name) / "tokens.yaml")
        store.save(ME_ACCOUNT, "good")
        app = YafyafApp("http://localhost:3000", Config(theme="onedark"), store)
        self.assertEqual(app.get_css_variables()["bg"], load_palette("onedark")["bg"])
        colors = None

        async def main():
            nonlocal colors
            with no_server(), patched_me(), patched_list():
                async with app.run_test() as pilot:
                    app.apply_theme("dracula")
                    await pilot.pause()
                    colors = app.query_one(YafsTable)._colors

        asyncio.run(main())
        self.assertEqual(app.get_css_variables()["bg"], load_palette("dracula")["bg"])
        # The list bakes its colors into Rich text, so a theme change has to reach it too
        self.assertEqual(colors.tag, load_palette("dracula")["purple"])


if __name__ == "__main__":
    unittest.main()
