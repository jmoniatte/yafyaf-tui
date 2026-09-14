import stat
import tempfile
import unittest
from pathlib import Path

from yafyaf_tui.config import Config, TokenStore, load_config


class LoadConfigTest(unittest.TestCase):
    def test_reads_settings_and_strips_trailing_slash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("theme: onelight\nurl: http://localhost:3000/\n")
            config = load_config(path)

        self.assertEqual(config.theme, "onelight")
        self.assertEqual(config.url, "http://localhost:3000")
        self.assertTrue(config.is_complete)
        self.assertEqual(config.warnings, [])

    def test_missing_file_and_missing_settings_are_reported(self) -> None:
        missing = load_config(Path("/nonexistent/config.yaml"))
        self.assertFalse(missing.is_complete)
        self.assertEqual(len(missing.warnings), 1)
        self.assertIn("not found", missing.warnings[0])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("theme: onedark\n")
            partial = load_config(path)
        self.assertFalse(partial.is_complete)
        self.assertEqual(partial.warnings, ["Missing setting: url"])

    def test_invalid_yaml_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("url: [unclosed\n")
            config = load_config(path)
        self.assertEqual(config.theme, Config().theme)
        self.assertEqual(len(config.warnings), 1)
        self.assertIn("not valid YAML", config.warnings[0])


class TokenStoreTest(unittest.TestCase):
    def test_round_trips_the_token_in_a_user_only_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TokenStore(Path(tmp) / "nested" / "token")
            self.assertEqual(store.load(), "")

            store.save("abc123")
            self.assertEqual(store.load(), "abc123")
            self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600)

            store.save("replaced")
            self.assertEqual(store.load(), "replaced")

            store.clear()
            store.clear()
            self.assertEqual(store.load(), "")
