import stat
import tempfile
import unittest
from pathlib import Path

from yafyaf_tui.config import DEFAULT_URL, Config, TokenStore, load_config, resolve_url, save_theme


class LoadConfigTest(unittest.TestCase):
    def test_reads_theme_and_treats_missing_file_as_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("theme: one-light\n")
            config = load_config(path)
        self.assertEqual(config.theme, "one-light")
        self.assertEqual(config.warnings, [])

        missing = load_config(Path("/nonexistent/config.yaml"))
        self.assertEqual(missing, Config())

    def test_a_theme_that_is_not_installed_warns_with_a_near_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("theme: onelight\n")
            config = load_config(path)
        self.assertEqual(config.theme, Config().theme)
        self.assertEqual(len(config.warnings), 1)
        self.assertIn("'onelight' is not installed", config.warnings[0])
        self.assertIn("one-light", config.warnings[0])


class SaveThemeTest(unittest.TestCase):
    def test_replaces_the_theme_line_and_leaves_the_rest_of_the_file_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            save_theme("dracula", path)
            self.assertEqual(path.read_text(), "theme: dracula\n")

            path.write_text("# my config\ntheme: onedark\nsomething: else\n")
            save_theme("dracula", path)
            self.assertEqual(path.read_text(), "# my config\ntheme: dracula\nsomething: else\n")
            self.assertEqual(load_config(path).theme, "dracula")

            path.write_text("something: else\n")
            save_theme("nord", path)
            self.assertEqual(path.read_text(), "theme: nord\nsomething: else\n")

    def test_invalid_file_falls_back_to_defaults_with_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("theme: [unclosed\n")
            broken = load_config(path)
            path.write_text("- just\n- a list\n")
            not_a_mapping = load_config(path)

        self.assertEqual(broken.theme, Config().theme)
        self.assertEqual(len(broken.warnings), 1)
        self.assertIn("not valid YAML", broken.warnings[0])
        self.assertEqual(not_a_mapping.warnings, ["Config file must contain a mapping of settings"])


class ResolveUrlTest(unittest.TestCase):
    def test_flag_beats_environment_beats_default(self) -> None:
        self.assertEqual(resolve_url(None, {}), DEFAULT_URL)
        self.assertEqual(resolve_url(None, {"YAFYAF_URL": "http://localhost:3000/"}), "http://localhost:3000")
        self.assertEqual(
            resolve_url("http://localhost:3100", {"YAFYAF_URL": "http://localhost:3000"}),
            "http://localhost:3100",
        )
        self.assertEqual(resolve_url("", {"YAFYAF_URL": ""}), DEFAULT_URL)


class TokenStoreTest(unittest.TestCase):
    def test_file_is_named_after_the_server(self) -> None:
        directory = Path("/tokens")
        self.assertEqual(TokenStore.for_url(DEFAULT_URL, directory).path, directory / "yafyaf.com")
        self.assertEqual(TokenStore.for_url("http://localhost:3000", directory).path, directory / "localhost_3000")
        self.assertEqual(TokenStore.for_url("https://yafyaf.com:443", directory).path, directory / "yafyaf.com_443")

    def test_round_trips_the_token_in_a_user_only_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TokenStore.for_url("http://localhost:3000", Path(tmp) / "tokens")
            self.assertEqual(store.load(), "")

            store.save("abc123")
            self.assertEqual(store.load(), "abc123")
            self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600)

            store.save("replaced")
            self.assertEqual(store.load(), "replaced")

            store.clear()
            store.clear()
            self.assertEqual(store.load(), "")
