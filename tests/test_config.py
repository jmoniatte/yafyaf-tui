import tempfile
import unittest
from pathlib import Path

from yafyaf_tui.config import Config, load_config


class LoadConfigTest(unittest.TestCase):
    def test_reads_settings_and_strips_trailing_slash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("theme: onelight\nurl: http://localhost:3000/\ntoken: abc\n")
            config = load_config(path)

        self.assertEqual(config.theme, "onelight")
        self.assertEqual(config.url, "http://localhost:3000")
        self.assertEqual(config.token, "abc")
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
        self.assertEqual(partial.warnings, ["Missing setting: url", "Missing setting: token"])

    def test_invalid_yaml_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("url: [unclosed\n")
            config = load_config(path)
        self.assertEqual(config.theme, Config().theme)
        self.assertEqual(len(config.warnings), 1)
        self.assertIn("not valid YAML", config.warnings[0])
