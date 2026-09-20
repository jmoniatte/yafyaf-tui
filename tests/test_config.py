import stat
import tempfile
import unittest
from pathlib import Path

from yafyaf_tui.config import DEFAULT_URL, Account, Config, TokenStore, load_config, resolve_url, save_theme
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


class TokenStoreTest(unittest.TestCase):
    def test_keeps_every_account_in_one_user_only_file_and_which_one_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TokenStore(Path(tmp) / "tokens.yaml")
            me = Account(DEFAULT_URL, "me@example.com")
            me_local = Account("http://localhost:3000", "me@example.com")
            other = Account(DEFAULT_URL, "other@example.com")
            self.assertEqual((store.current(), store.accounts(), store.token(me)), (None, [], ""))

            store.save(me, "abc123")
            self.assertEqual((store.current(), store.token(me)), (me, "abc123"))
            self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600)

            # The same email on another server is another account; the last login is current
            store.save(me_local, "local")
            store.save(other, "def456")
            self.assertEqual(store.accounts(), [me, me_local, other])
            self.assertEqual(store.current(), other)
            self.assertEqual(store.accounts_on(DEFAULT_URL), [me, other])
            store.select(me_local)
            self.assertEqual(store.token(store.current()), "local")
            store.save(me, "replaced")
            self.assertEqual((store.token(me), store.accounts()), ("replaced", [me_local, other, me]))

            # Which account a server starts on: by email, else the current one, else the first stored there
            self.assertEqual(store.resolve(DEFAULT_URL, "other@example.com"), other)
            self.assertEqual(store.resolve(DEFAULT_URL, "nobody@example.com"), None)
            self.assertEqual(store.resolve(DEFAULT_URL), me)
            self.assertEqual(store.resolve("http://localhost:3000"), me_local)
            self.assertEqual(store.resolve("http://localhost:4000"), None)
            self.assertEqual(store.find("me@example.com"), me_local)

            # Clearing the current account moves to another on the same server first, then anywhere, then nothing
            store.clear(me)
            self.assertEqual(store.current(), other)
            store.clear(other)
            self.assertEqual(store.current(), me_local)
            store.clear(me_local)
            store.clear(None)
            self.assertEqual((store.current(), store.accounts()), (None, []))

            self.assertEqual(Account(DEFAULT_URL, "me@example.com").label, "me@example.com")
            self.assertEqual(me_local.label, "me@example.com (localhost:3000)")

    def test_imports_the_per_file_layout_of_older_versions_and_removes_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "tokens"
            (legacy / "yafyaf.com").mkdir(parents=True)
            (legacy / "yafyaf.com" / "me@example.com").write_text("prod\n")
            (legacy / "yafyaf.com" / "sayings@example.com").write_text("say\n")
            (legacy / "yafyaf.com" / "current").write_text("sayings@example.com\n")
            (legacy / "localhost_3000").mkdir()
            (legacy / "localhost_3000" / "me@example.com").write_text("local\n")
            (legacy / "localhost_3000" / "current").write_text("me@example.com\n")
            (legacy / "dev.example.com").write_text("no-email\n")  # The oldest layout: one token, no email

            store = TokenStore(Path(tmp) / "tokens.yaml")
            store.import_legacy(legacy)
            self.assertEqual(
                store.accounts(),
                [
                    Account("http://localhost:3000", "me@example.com"),
                    Account(DEFAULT_URL, "me@example.com"),
                    Account(DEFAULT_URL, "sayings@example.com"),
                ],
            )
            self.assertEqual(store.token(Account(DEFAULT_URL, "sayings@example.com")), "say")
            self.assertEqual(store.current(), Account(DEFAULT_URL, "sayings@example.com"))
            self.assertFalse(legacy.exists())

            # Nothing to import the second time round
            store.import_legacy(legacy)
            self.assertEqual(len(store.accounts()), 3)

    def test_a_corrupt_or_odd_file_reads_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TokenStore(Path(tmp) / "tokens.yaml")
            store.path.write_text("accounts: [nope, {url: 1}]\ncurrent: yes\n")
            self.assertEqual((store.current(), store.accounts()), (None, []))
            store.path.write_text("- - [")
            self.assertEqual(store.accounts(), [])
