import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, Input, Select, Static

from yafyaf_tui.accounts import Account, TokenStore
from yafyaf_tui.api import (
    ApiConnectionError,
    AuthenticationError,
    NotFoundError,
    Session,
)
from yafyaf_tui.app import YafyafApp
from yafyaf_tui.config import DEFAULT_URL, Config
from ouikit.dialog import ConfirmDialog
from ouikit.theme import load_palette

from yafyaf_tui.screens import LoginScreen, SettingsScreen
from yafyaf_tui.screens.settings_screen import ADD_ACCOUNT
from yafyaf_tui.widgets import OfflineNotice, YafsTable, YafsView

from support import ME, ME_ACCOUNT, OTHER, OTHER_ACCOUNT, SAYINGS, SAYINGS_ACCOUNT, URL, header_message, patched_list, patched_me, row_text, settle

class SessionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TokenStore(Path(self.tmp.name) / "tokens.yaml")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _app(self, url: str = "http://localhost:3000") -> YafyafApp:
        return YafyafApp(url, Config(), self.store)

    def test_saved_token_is_checked_and_user_is_shown(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            with patched_me() as me, patched_list() as list_yafs:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    me.assert_called_once()
                    list_yafs.assert_called_once_with("", 1)
                    self.assertNotIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.user, ME)
                    self.assertFalse(app.query("#btn-sign-out"))  # it lives in Settings now
                    table = app.query_one(YafsTable)
                    self.assertEqual(table.row_count, 2)
                    self.assertEqual(row_text(table, 0), ["2026-09-13", "First yaf"])
                    date_cell = table.get_row_at(0)[0]
                    self.assertEqual(str(date_cell.style), load_palette("onedark")["comment"])
                    self.assertEqual(app.query_one("#yafs-status", Static).content, "2 yafs")
                    # The count shares the column header line, right-aligned
                    status = app.query_one("#yafs-status", Static)
                    self.assertEqual(status.region.y, app.query_one("#yafs-header-summary").region.y)
                    self.assertEqual(status.region.right, table.region.right)

        asyncio.run(exercise())

    def test_login_saves_the_token_and_shows_the_user(self) -> None:
        async def exercise() -> None:
            app = self._app()
            session = Session(user=ME, token="fresh")
            with patch("yafyaf_tui.api.client.YafyafClient.login", return_value=session) as login, patched_list():
                async with app.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    self.assertIsInstance(app.screen, LoginScreen)

                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIs(app.screen.focused, app.screen.query_one("#password", Input))
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertEqual(
                        app.screen.query_one("#login-error", Static).content,
                        "Email and password are required",
                    )

                    app.screen.query_one("#email", Input).value = "me@example.com"
                    app.screen.query_one("#password", Input).value = "secret"
                    app.screen.query_one("#password", Input).focus()
                    await pilot.press("enter")
                    await settle(app, pilot)

                    login.assert_called_once_with("me@example.com", "secret")
                    self.assertNotIsInstance(app.screen, LoginScreen)
                    self.assertEqual(self.store.token(self.store.current()), "fresh")
                    self.assertEqual(app.client.token, "fresh")
                    self.assertEqual(app.user, ME)
                    self.assertEqual(app.query_one(YafsTable).row_count, 2)

        asyncio.run(exercise())

    def test_settings_signs_out_after_confirming_and_forgets_the_token(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            unreachable = ApiConnectionError("Cannot reach http://localhost:3000")
            logout = patch("yafyaf_tui.api.client.YafyafClient.logout", side_effect=unreachable)
            with patched_me(), patched_list(), logout as revoke:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    await pilot.press(",")
                    await pilot.pause()
                    self.assertEqual(app.screen.query_one("#account-selector", Select).value, ME_ACCOUNT)

                    await pilot.click("#btn-sign-out")
                    await settle(app, pilot)
                    # Settings closes first, so the confirmation is not stacked on top of it
                    self.assertIsInstance(app.screen, ConfirmDialog)
                    self.assertEqual(len(app.screen_stack), 2)
                    message = app.screen.query_one("#dialog-message", Static).content
                    self.assertEqual(message, "You are signed in as me@example.com (localhost:3000)")
                    await pilot.press("escape")
                    await settle(app, pilot)
                    revoke.assert_not_called()
                    self.assertEqual(self.store.token(self.store.current()), "good")
                    self.assertTrue(app.query_one(YafsTable).has_focus)

                    await pilot.press(",")
                    await pilot.pause()
                    await pilot.click("#btn-sign-out")
                    await settle(app, pilot)
                    await pilot.click("#confirm-btn")
                    await settle(app, pilot)
                    # The server could not revoke the token, but it is forgotten locally all the same
                    revoke.assert_called_once()
                    self.assertEqual(self.store.token(self.store.current()), "")
                    self.assertEqual(app.client.token, "")
                    self.assertIsNone(app.user)
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.query_one(YafsTable).row_count, 0)
                    self.assertEqual(app.query_one("#yafs-status", Static).content, "")

        asyncio.run(exercise())

    def test_an_unreachable_server_still_offers_sign_out_to_clear_the_token(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            unreachable = ApiConnectionError("Cannot reach http://localhost:3000")
            with patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=unreachable), \
                 patch("yafyaf_tui.api.client.YafyafClient.logout", side_effect=unreachable):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertIsNone(app.user)
                    await pilot.press(",")
                    await pilot.pause()
                    self.assertEqual(app.screen.query_one("#account-selector", Select).value, ME_ACCOUNT)

                    await pilot.click("#btn-sign-out")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmDialog)
                    message = app.screen.query_one("#dialog-message", Static).content
                    self.assertEqual(message, "You are signed in as me@example.com (localhost:3000)")
                    await pilot.click("#confirm-btn")
                    await settle(app, pilot)
                    self.assertEqual(self.store.accounts(), [])
                    self.assertIsInstance(app.screen, LoginScreen)

        asyncio.run(exercise())

    def test_an_unavailable_server_hides_the_list_until_a_retry_succeeds(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            answers = [NotFoundError(404, "Not Found"), ApiConnectionError("Cannot reach it: refused"), ME]
            with patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=answers), patched_list():
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertIsNone(app.user)
                    notice = app.query_one(OfflineNotice)
                    self.assertTrue(notice.display)
                    self.assertFalse(app.query_one(YafsView).display)
                    self.assertEqual(app.query_one("#offline-title", Static).content, "localhost:3000 is not available")
                    self.assertEqual(app.query_one("#offline-detail", Static).content, "The server answered 404: Not Found")
                    # The list's keys are gone with it; only the app's own keys remain
                    with patch.object(app, "_edit_yaf") as edit:
                        await pilot.press("n")
                        await pilot.pause()
                        edit.assert_not_called()
                    await pilot.press(",")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, SettingsScreen)
                    await pilot.press("escape")
                    await pilot.pause()

                    await pilot.press("r")
                    await settle(app, pilot)
                    self.assertTrue(notice.display)
                    self.assertEqual(app.query_one("#offline-detail", Static).content, "Cannot reach it: refused")

                    await pilot.click("#btn-retry")
                    await settle(app, pilot)
                    self.assertEqual(app.user, ME)
                    self.assertFalse(notice.display)
                    self.assertTrue(app.query_one(YafsView).display)
                    self.assertEqual(app.query_one(YafsTable).row_count, 2)
                    self.assertIs(app.focused, app.query_one(YafsTable))

        asyncio.run(exercise())

    def test_settings_switches_between_stored_accounts_and_adds_one(self) -> None:
        async def exercise() -> None:
            self.store.save(SAYINGS_ACCOUNT, "sayings-token")
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            app.animation_level = "none"
            users = {"good": ME, "sayings-token": SAYINGS, "fresh": OTHER}

            def me_for_token():
                app.client.score = {"good": 94, "sayings-token": 3, "fresh": 1}[app.client.token]
                app.client.on_response()
                return users[app.client.token]

            with (
                patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=me_for_token),
                patched_list() as list_yafs,
                patch("yafyaf_tui.api.client.YafyafClient.login", return_value=Session(user=OTHER, token="fresh")),
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertEqual(app.user, ME)
                    self.assertEqual(app.query_one("#app-account", Static).content, ME.email)
                    self.assertEqual(app.query_one("#header-score", Static).content, "94")

                    await pilot.press(",")
                    await pilot.pause()
                    selector = app.screen.query_one("#account-selector", Select)
                    self.assertEqual(selector.value, ME_ACCOUNT)
                    self.assertEqual(
                        [label for label, _ in selector._options], [SAYINGS_ACCOUNT.label, ME_ACCOUNT.label, "Add account..."]
                    )

                    # Switching reloads the list as the other account, settings stays open
                    selector.value = SAYINGS_ACCOUNT
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, SettingsScreen)
                    self.assertEqual(app.user, SAYINGS)
                    self.assertEqual(app.client.token, "sayings-token")
                    self.assertEqual(self.store.current(), SAYINGS_ACCOUNT)
                    self.assertEqual(app.query_one("#app-account", Static).content, SAYINGS.email)
                    self.assertEqual(app.query_one("#header-score", Static).content, "3")
                    self.assertEqual(list_yafs.call_count, 2)

                    # Adding an account closes settings and asks to log in; cancelling keeps the current one
                    selector.value = ADD_ACCOUNT
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.screen.query_one("#cancel-btn", Button).label, "Cancel")
                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertEqual(len(app.screen_stack), 1)
                    self.assertEqual((app.user, app.client.token), (SAYINGS, "sayings-token"))

                    await pilot.press(",")
                    await pilot.pause()
                    app.screen.query_one("#account-selector", Select).value = ADD_ACCOUNT
                    await settle(app, pilot)
                    app.screen.query_one("#email", Input).value = OTHER.email
                    app.screen.query_one("#password", Input).value = "secret"
                    app.screen.query_one("#password", Input).focus()
                    await pilot.press("enter")
                    await settle(app, pilot)
                    self.assertEqual(app.user, OTHER)
                    self.assertEqual(self.store.accounts(), [SAYINGS_ACCOUNT, ME_ACCOUNT, OTHER_ACCOUNT])
                    self.assertEqual(self.store.current(), OTHER_ACCOUNT)

                    # Signing out of one account falls back to another instead of asking to log in
                    with patch("yafyaf_tui.api.client.YafyafClient.logout"):
                        app.confirm_sign_out()
                        await pilot.pause()
                        await pilot.click("#confirm-btn")
                        await settle(app, pilot)
                    self.assertNotIsInstance(app.screen, LoginScreen)
                    self.assertEqual(self.store.accounts(), [SAYINGS_ACCOUNT, ME_ACCOUNT])
                    self.assertEqual(app.account, self.store.current())
                    self.assertEqual(app.user.email, app.account.email)

        asyncio.run(exercise())

    def test_s_cycles_through_the_stored_accounts(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            app = self._app()
            app.animation_level = "none"
            users = {"good": ME, "sayings-token": SAYINGS}
            with (
                patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=lambda: users[app.client.token]),
                patched_list() as list_yafs,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    # With one account there is nothing to cycle to
                    await pilot.press("s")
                    await settle(app, pilot)
                    self.assertEqual((app.user, header_message(app)), (ME, ""))

                    self.store.save(SAYINGS_ACCOUNT, "sayings-token")
                    self.store.select(ME_ACCOUNT)
                    for expected in (SAYINGS, ME, SAYINGS):
                        await pilot.press("s")
                        await settle(app, pilot)
                        self.assertEqual(app.user, expected)
                        self.assertEqual(self.store.current(), Account(URL, expected.email))
                        self.assertEqual(app.query_one("#app-account", Static).content, expected.email)
                        self.assertEqual(header_message(app), f"Switched to {Account(URL, expected.email).label}")
                    self.assertEqual(list_yafs.call_count, 4)

        asyncio.run(exercise())

    def test_accounts_on_other_servers_are_listed_and_switching_moves_the_client_there(self) -> None:
        async def exercise() -> None:
            production = Account(DEFAULT_URL, ME.email)
            self.store.save(production, "prod-token")
            self.store.save(ME_ACCOUNT, "good")
            config = Config(servers=[DEFAULT_URL, URL])
            app = YafyafApp(URL, config, self.store)
            app.animation_level = "none"
            users = {"good": ME, "prod-token": ME, "fresh": OTHER}
            with (
                patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=lambda: users[app.client.token]),
                patched_list() as list_yafs,
                patch("yafyaf_tui.api.client.YafyafClient.login", return_value=Session(user=OTHER, token="fresh")) as login,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertEqual((app.url, app.client.base_url), (URL, URL))
                    self.assertEqual(app.query_one("#app-url", Static).content, "localhost:3000")

                    # s moves to the production account: the client, header and server label follow
                    await pilot.press("s")
                    await settle(app, pilot)
                    self.assertEqual((app.account, app.client.base_url, app.client.token), (production, DEFAULT_URL, "prod-token"))
                    self.assertFalse(app.query_one("#app-url").display)
                    self.assertEqual(header_message(app), f"Switched to {ME.email}")
                    self.assertEqual(list_yafs.call_count, 2)

                    await pilot.press(",")
                    await pilot.pause()
                    selector = app.screen.query_one("#account-selector", Select)
                    self.assertEqual(
                        [label for label, _ in selector._options],
                        [ME.email, f"{ME.email} (localhost:3000)", "Add account..."],
                    )

                    # Adding an account asks which server, defaulting to the one in use
                    selector.value = ADD_ACCOUNT
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, LoginScreen)
                    server = app.screen.query_one("#login-server", Select)
                    self.assertEqual(server.value, DEFAULT_URL)
                    self.assertEqual([label for label, _ in server._options], ["yafyaf.com", "localhost:3000"])
                    server.value = URL
                    app.screen.query_one("#email", Input).value = OTHER.email
                    app.screen.query_one("#password", Input).value = "secret"
                    app.screen.query_one("#password", Input).focus()
                    await pilot.press("enter")
                    await settle(app, pilot)
                    login.assert_called_once_with(OTHER.email, "secret")
                    self.assertEqual((app.account, app.client.base_url), (OTHER_ACCOUNT, URL))
                    self.assertEqual(self.store.current(), OTHER_ACCOUNT)
                    self.assertEqual(app.query_one("#app-url", Static).content, "localhost:3000")

                # With one server there is no dropdown, just the server's name
                self.store.clear(production)
                self.store.clear(OTHER_ACCOUNT)
                self.store.clear(ME_ACCOUNT)
                app = YafyafApp(URL, Config(servers=[URL]), self.store)
                async with app.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertFalse(app.screen.query("#login-server"))
                    self.assertEqual(app.screen.query_one("#login-url", Static).content, URL)

        asyncio.run(exercise())

    def test_the_as_flag_picks_the_account_and_prefills_the_login_when_it_has_no_token(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            self.store.save(SAYINGS_ACCOUNT, "sayings-token")
            with patched_me() as me, patched_list():
                app = YafyafApp(URL, Config(), self.store, account=ME_ACCOUNT)
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    me.assert_called_once()
                    self.assertEqual(app.client.token, "good")

                app = YafyafApp(URL, Config(), self.store, login_email=OTHER.email)
                async with app.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.screen.query_one("#email", Input).value, OTHER.email)
                    self.assertIs(app.screen.focused, app.screen.query_one("#password", Input))

        asyncio.run(exercise())

    def test_rejected_token_falls_back_to_another_account_when_there_is_one(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "good")
            self.store.save(SAYINGS_ACCOUNT, "stale")
            app = self._app()
            error = AuthenticationError(401, "Authentication is required and has failed")

            def me_for_token():
                if app.client.token == "stale":
                    raise error
                return ME

            with patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=me_for_token), patched_list():
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)
                    self.assertNotIsInstance(app.screen, LoginScreen)
                    self.assertEqual(app.user, ME)
                    self.assertEqual(self.store.accounts(), [ME_ACCOUNT])
                    self.assertIn("rejected", header_message(app))

        asyncio.run(exercise())

    def test_rejected_token_is_cleared_and_login_is_asked_again(self) -> None:
        async def exercise() -> None:
            self.store.save(ME_ACCOUNT, "stale")
            app = self._app()
            error = AuthenticationError(401, "Authentication is required and has failed")
            with patch("yafyaf_tui.api.client.YafyafClient.me", side_effect=error):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, LoginScreen)
                    self.assertEqual(self.store.token(self.store.current()), "")
                    self.assertIn("rejected", app.screen.query_one("#login-error", Static).content)

                    await pilot.press("escape")
                    await pilot.pause()
            self.assertEqual(app.return_code, 0)

        asyncio.run(exercise())
