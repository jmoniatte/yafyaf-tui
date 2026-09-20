import tempfile
import unittest
from pathlib import Path

from yafyaf_tui.config import DEFAULT_URL, Config, load_config, resolve_url, save_theme
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

    def test_servers_list_the_login_choices_and_bad_entries_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("servers:\n  - https://yafyaf.com/\n  - http://localhost:3000\n  - localhost\n  - http://localhost:3000\n")
            config = load_config(path)
            self.assertEqual(config.servers, [DEFAULT_URL, "http://localhost:3000"])
            self.assertEqual(config.warnings, ["servers: 'localhost' is not a URL, ignoring it"])
            self.assertEqual(config.servers_with("http://localhost:3000"), config.servers)
            self.assertEqual(config.servers_with("http://dev:4000"), ["http://dev:4000", DEFAULT_URL, "http://localhost:3000"])

            path.write_text("servers: yafyaf.com\n")
            config = load_config(path)
            self.assertEqual((config.servers, config.warnings), ([DEFAULT_URL], ["servers: must be a list of URLs"]))
            self.assertEqual(Config().servers, [DEFAULT_URL])

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
