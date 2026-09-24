import contextlib
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from yafyaf_tui import __version__
from yafyaf_tui.__main__ import main
from yafyaf_tui.accounts import Account, TokenStore
from yafyaf_tui.api import (
    ApiConnectionError,
    AuthenticationError,
    Yaf,
    YafyafClient,
)
from yafyaf_tui.commands import new_yaf
from yafyaf_tui.config import DEFAULT_URL, Config

from support import ME_ACCOUNT, python_editor

class MainTest(unittest.TestCase):
    def test_version_flag_exits_without_starting_the_tui(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"YafYaf TUI {__version__}")

    def test_url_flag_and_environment_pick_the_server(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("yafyaf_tui.__main__.YafyafApp") as app_class,
            patch("yafyaf_tui.__main__.start", side_effect=lambda name, make_app: make_app().run()) as start,
            patch("yafyaf_tui.__main__.TokenStore.default", return_value=TokenStore(Path(tmp) / "tokens.yaml")),
            patch("yafyaf_tui.__main__.load_config", return_value=Config()),
        ):
            with patch.dict("os.environ", {"YAFYAF_URL": ""}):
                main([])
            with patch.dict("os.environ", {"YAFYAF_URL": "http://localhost:3000"}):
                main([])
                main(["--url", "http://localhost:3100/", "--as", "me@example.com"])
        urls = [call.kwargs["url"] for call in app_class.call_args_list]
        self.assertEqual(urls, [DEFAULT_URL, "http://localhost:3000", "http://localhost:3100"])
        self.assertEqual([call.kwargs["account"] for call in app_class.call_args_list], [None, None, None])
        self.assertEqual([call.kwargs["login_email"] for call in app_class.call_args_list], ["", "", "me@example.com"])
        self.assertEqual(app_class.return_value.run.call_count, 3)
        self.assertEqual(start.call_count, 3)

    def test_new_command_creates_a_yaf_without_starting_the_tui(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("yafyaf_tui.__main__.YafyafApp") as app_class,
            patch("yafyaf_tui.__main__.new_yaf", return_value=0) as command,
            patch("yafyaf_tui.__main__.start") as start,
            patch("yafyaf_tui.__main__.TokenStore.default", return_value=TokenStore(Path(tmp) / "tokens.yaml")),
            patch("yafyaf_tui.__main__.load_config", return_value=Config()),
            self.assertRaises(SystemExit) as raised,
        ):
            main(["new", "--url", "http://localhost:3100", "--as", "sayings@example.com"])
        start.assert_not_called()
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(command.call_args.args[0], "http://localhost:3100")
        self.assertEqual(command.call_args.args[1].path.name, "tokens.yaml")
        self.assertEqual(command.call_args.kwargs, {"email": "sayings@example.com", "url_given": True})
        app_class.assert_not_called()


class NewYafTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TokenStore(Path(self.tmp.name) / "tokens.yaml")
        self.store.save(ME_ACCOUNT, "good")
        self.record = Path(self.tmp.name) / "draft-path"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, text: str, **create) -> tuple[int, str, str, Path | None]:
        """Run `yaf new` with an editor that writes text into the draft and records its path."""
        script = (
            "import pathlib, sys; "
            f"pathlib.Path({str(self.record)!r}).write_text(sys.argv[1]); "
            f"pathlib.Path(sys.argv[1]).write_text({text!r})"
        )
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.dict("os.environ", {"VISUAL": python_editor(script)}),
            patch("yafyaf_tui.api.client.YafyafClient.create_yaf", **create) as self.create_yaf,
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = new_yaf("http://localhost:3000", self.store, date(2026, 9, 14))
        draft = Path(self.record.read_text()) if self.record.exists() else None
        return code, out.getvalue(), err.getvalue(), draft

    def test_new_yaf_is_created_from_the_editor_unless_left_empty(self) -> None:
        saved = Yaf(id="y3", content="A new yaf", date=date(2026, 9, 14))
        code, out, _, draft = self._run("A new yaf\n", return_value=saved)
        self.assertEqual(code, 0)
        self.create_yaf.assert_called_once_with("A new yaf", date(2026, 9, 14))
        self.assertEqual(out.strip(), "Saved yaf for 2026-09-14.")
        self.assertRegex(draft.name, r"^yaf-new-\w+\.md$")
        self.assertFalse(draft.exists())

        # The editor starts from front matter holding the given day, and a changed date is used
        code, out, _, draft = self._run("---\ndate: 2026-09-13\n---\n\nYesterday\n", return_value=saved)
        self.create_yaf.assert_called_once_with("Yesterday", date(2026, 9, 13))
        self.assertEqual(out.strip(), "Saved yaf for 2026-09-13.")

        code, out, _, draft = self._run("---\ndate: 2026-09-14\n---\n\n")
        self.assertEqual(code, 0)
        self.create_yaf.assert_not_called()
        self.assertEqual(out.strip(), "Empty yaf, nothing saved.")
        self.assertFalse(draft.exists())

    def test_the_server_saying_is_printed_after_saving(self) -> None:
        def note_saying(*args):
            # What the real client does inside request
            client.saying = "There is always time."
            return Yaf(id="y3", content="A new yaf", date=date(2026, 9, 14))

        client = YafyafClient("http://localhost:3000", "good")
        with patch("yafyaf_tui.commands.YafyafClient", return_value=client):
            code, out, _, _ = self._run("A new yaf\n", side_effect=note_saying)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["Saved yaf for 2026-09-14.", "There is always time."])

    def test_failures_keep_the_draft_and_exit_with_an_error(self) -> None:
        code, _, err, draft = self._run("Lost?", side_effect=ApiConnectionError("Cannot reach it"))
        self.assertEqual(code, 1)
        self.assertIn(f"Cannot reach it\nYour yaf is kept in {draft}", err)
        self.assertEqual(draft.read_text(), "Lost?")
        draft.unlink()

        code, _, err, draft = self._run("---\ndate: soon\n---\nLost?")
        self.assertEqual(code, 1)
        self.create_yaf.assert_not_called()
        self.assertIn(f"An invalid date was entered\nYour yaf is kept in {draft}", err)
        draft.unlink()

        code, _, err, draft = self._run("Lost?", side_effect=AuthenticationError(401, "rejected"))
        self.assertEqual(code, 1)
        self.assertIn("Run yaf to log in again", err)
        self.assertTrue(draft.exists())
        self.assertEqual(self.store.token(self.store.current()), "")
        draft.unlink()

        # The rejected token was cleared, so the next run stops before opening the editor
        self.record.unlink()
        code, _, err, draft = self._run("Unused")
        self.assertEqual(code, 1)
        self.assertIn("Run yaf to log in first", err)
        self.assertIsNone(draft)

        self.store.save(ME_ACCOUNT, "good")
        err = io.StringIO()
        with patch.dict("os.environ", {"VISUAL": python_editor("raise SystemExit(3)")}), contextlib.redirect_stderr(err):
            self.assertEqual(new_yaf("http://localhost:3000", self.store), 1)
        self.assertIn("exited with status 3", err.getvalue())

    def test_as_email_finds_the_account_on_another_server_unless_the_server_was_given(self) -> None:
        self.store.save(Account("http://dev:4000", "dev@example.com"), "dev-token")
        quiet = contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())
        with patch("yafyaf_tui.api.client.YafyafClient.create_yaf") as create_yaf, quiet[0], quiet[1]:
            with patch.dict("os.environ", {"VISUAL": python_editor("import pathlib, sys; pathlib.Path(sys.argv[1]).write_text('Hi')")}):
                self.assertEqual(new_yaf("http://localhost:3000", self.store, email="dev@example.com"), 0)
                self.assertEqual(new_yaf("http://localhost:3000", self.store, email="dev@example.com", url_given=True), 1)
        create_yaf.assert_called_once()
        self.assertEqual(self.store.starting_account("http://localhost:3000", "dev@example.com"), Account("http://dev:4000", "dev@example.com"))
        self.assertIsNone(self.store.starting_account("http://localhost:3000", "dev@example.com", url_given=True))
        self.assertEqual(self.store.starting_account("http://localhost:3000"), ME_ACCOUNT)
