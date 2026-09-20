import stat
import tempfile
import unittest
from pathlib import Path

from yafyaf_tui.accounts import Account, TokenStore
from yafyaf_tui.config import DEFAULT_URL


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
