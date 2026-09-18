import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from yafyaf_tui.config import DEFAULT_URL, Config, TokenStore, load_config, resolve_url, save_theme
from yafyaf_tui.theme import default_theme


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
        self.assertEqual(config.theme, default_theme())
        self.assertEqual(len(config.warnings), 1)
        self.assertIn("'onelight' is not installed", config.warnings[0])
        self.assertIn("one-light", config.warnings[0])

    def test_terminal_theme_is_the_default_and_always_accepted(self) -> None:
        self.assertEqual(Config().theme, "terminal")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("theme: terminal\n")
            config = load_config(path)
        self.assertEqual(config.theme, "terminal")
        self.assertEqual(config.warnings, [])


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
    def test_directory_is_named_after_the_server(self) -> None:
        directory = Path("/tokens")
        self.assertEqual(TokenStore.for_url(DEFAULT_URL, directory).path, directory / "yafyaf.com")
        self.assertEqual(TokenStore.for_url("http://localhost:3000", directory).path, directory / "localhost_3000")
        self.assertEqual(TokenStore.for_url("https://yafyaf.com:443", directory).path, directory / "yafyaf.com_443")

    def test_keeps_one_user_only_file_per_account_and_which_one_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TokenStore.for_url("http://localhost:3000", Path(tmp) / "tokens")
            self.assertEqual((store.load(), store.current(), store.accounts()), ("", "", []))

            store.save("abc123", "me@example.com")
            self.assertEqual((store.load(), store.current()), ("abc123", "me@example.com"))
            self.assertEqual(stat.S_IMODE((store.path / "me@example.com").stat().st_mode), 0o600)

            # A second login becomes current; the first is still there to switch back to
            store.save("def456", "sayings@example.com")
            self.assertEqual((store.load(), store.current()), ("def456", "sayings@example.com"))
            self.assertEqual(store.accounts(), ["me@example.com", "sayings@example.com"])
            self.assertEqual(store.load("me@example.com"), "abc123")
            store.select("me@example.com")
            self.assertEqual(store.load(), "abc123")

            store.save("replaced", "me@example.com")
            self.assertEqual(store.load(), "replaced")

            # Clearing the current account moves on to the next one, then to nothing
            store.clear()
            self.assertEqual((store.load(), store.current()), ("def456", "sayings@example.com"))
            store.clear("sayings@example.com")
            store.clear()
            self.assertEqual((store.load(), store.current(), store.accounts()), ("", "", []))

    def test_a_legacy_single_file_token_is_read_until_it_is_saved_under_its_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TokenStore.for_url("http://localhost:3000", Path(tmp) / "tokens")
            store.path.parent.mkdir()
            store.path.write_text("legacy\n")
            self.assertEqual((store.load(), store.current(), store.accounts()), ("legacy", "", []))

            store.save("legacy", "me@example.com")
            self.assertTrue(store.path.is_dir())
            self.assertEqual((store.load(), store.current()), ("legacy", "me@example.com"))

            shutil.rmtree(store.path)
            store.path.write_text("legacy\n")
            store.clear()
            self.assertFalse(store.path.exists())
