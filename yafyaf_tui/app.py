import asyncio
from datetime import date
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.notifications import Notification, SeverityLevel

from .api import (
    ApiConnectionError,
    ApiError,
    AuthenticationError,
    NotFoundError,
    User,
    Yaf,
    YafyafClient,
)
from .config import DEFAULT_URL, Account, Config, TokenStore, load_config, save_theme, server_name
from .editor import Draft, DraftError, EditorError, Entry
from .screens import EDIT_AGAIN, RETRY, ConfirmDialog, Login, LoginScreen, NotSavedDialog, SettingsScreen, ThemePicker
from .shortcuts import GENERAL
from .theme import effective_theme, load_palette
from .widgets import (
    AppHeader,
    Echo,
    EditRequested,
    HeaderNotification,
    NewYafRequested,
    OfflineNotice,
    RetryRequested,
    SettingsRequested,
    ViewClosed,
    YafDetail,
    YafOpened,
    YafsTable,
    YafsView,
)

STYLES_DIR = Path(__file__).parent / "styles"


class YafyafApp(App):
    """Terminal client for the YafYaf notes API."""

    TITLE = "YafYaf"

    BINDINGS = [
        Binding("question_mark", "settings", "Settings", key_display="?", group=GENERAL),
        Binding("t", "show_themes", "Change theme", group=GENERAL),
        Binding("s", "next_account", "Switch account", group=GENERAL),
        Binding("q", "quit", "Quit", group=GENERAL),
    ]

    def __init__(
        self,
        url: str = DEFAULT_URL,
        config: Config | None = None,
        token_store: TokenStore | None = None,
        account: Account | None = None,
        login_email: str = "",
    ) -> None:
        self.config = config if config is not None else load_config()
        self.token_store = token_store if token_store is not None else TokenStore.default()
        # The account whose token is in use, or None until the first login; it names the server too
        self.account = account if (account or login_email) else self.token_store.resolve(url)
        self.url = self.account.url if self.account else url
        # Offered by the login screen; the server in use is always among them
        self.servers = self.config.servers_with(self.url)
        self._login_email = login_email
        self.client = YafyafClient(self.url, self.token_store.token(self.account))
        self.user: User | None = None
        # The yaf shown in place of the list, if any; the editor returns there when it started there
        self._viewing: Yaf | None = None
        # The palette is served from get_css_variables rather than baked into
        # CSS, so apply_theme can swap it without restarting.
        self._palette = load_palette(self.config.theme)
        self.CSS = (STYLES_DIR / "base.tcss").read_text()
        super().__init__()

    def compose(self) -> ComposeResult:
        yield AppHeader()
        yield YafsView(self.client, **self._rich_colors())
        yield YafDetail()
        yield OfflineNotice()
        yield Echo(self.client)

    def _rich_colors(self) -> dict[str, str]:
        """The palette entries the yaf list renders through Rich, where TCSS variables do not reach."""
        return {
            "date_color": self._palette["comment"],
            "link_color": self._palette["blue"],
            "heading_color": self._palette["yellow"],
        }

    def get_css_variables(self) -> dict[str, str]:
        """Serve the base16 palette to the stylesheet alongside Textual's own."""
        return {**super().get_css_variables(), **self._palette}

    def action_show_themes(self) -> None:
        """Browse themes, applying each one as the cursor moves."""
        self.push_screen(ThemePicker(effective_theme(self.config.theme)), callback=self._theme_chosen)

    def _theme_chosen(self, theme_name: str | None) -> None:
        if theme_name is not None:
            self.set_theme(theme_name)

    def set_theme(self, theme_name: str) -> None:
        """Apply a theme and remember it for next launch."""
        if effective_theme(theme_name) == effective_theme(self.config.theme):
            return
        self.apply_theme(theme_name)
        self.config.theme = theme_name
        save_theme(theme_name)
        self.notify(f"Theme set to {theme_name}")

    def apply_theme(self, theme_name: str) -> None:
        """Swap the palette and repaint in place."""
        self._palette = load_palette(theme_name)
        self.refresh_css()
        # refresh_css only re-applies TCSS; the list bakes its colors into Rich text
        self.query_one(YafsView).set_colors(**self._rich_colors())

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "information",
        timeout: float | None = None,
        markup: bool = False,
    ) -> None:
        """Show notifications in the header instead of as toasts.

        Messages carry server errors and file paths, which may contain brackets, so markup is never on.
        """
        notification = Notification(message, title, severity, self.NOTIFICATION_TIMEOUT if timeout is None else timeout)
        self.call_later(self._show_notification, notification)

    def _show_notification(self, notification: Notification) -> None:
        for screen in reversed(self.screen_stack):
            notifications = list(screen.query(HeaderNotification))
            if notifications:
                notifications[0].show_notification(notification)
                return
        super().notify(
            notification.message,
            title=notification.title,
            severity=notification.severity,
            timeout=max(notification.time_left, 0),
            markup=False,
        )

    def on_mount(self) -> None:
        for warning in self.config.warnings:
            self.notify(warning, severity="warning", timeout=10)
        self._show_account()
        if self.client.token:
            self._check_token()
        else:
            self._ask_login(email=self._login_email)

    @work(exclusive=True)
    async def _check_token(self) -> None:
        """Confirm the stored token still works before showing anything that needs it."""
        try:
            self.user = await asyncio.to_thread(self.client.me)
        except AuthenticationError:
            self.token_store.clear(self.account)
            self.client.token = ""
            self._use_next_account("Your saved token was rejected; please log in again.")
            return
        except ApiConnectionError as error:
            self._go_offline(str(error))
            return
        except ApiError as error:
            # A proxy answering for a server that is down, or a deploy in progress
            self._go_offline(f"The server answered {error.status}: {error}")
            return
        self.token_store.select(self.account)
        self._signed_in_as(self.user)

    def _ask_login(self, message: str = "", email: str = "", cancel_label: str = "Quit") -> None:
        screen = LoginScreen(self.servers, self.url, message, email=email, cancel_label=cancel_label)
        self.push_screen(screen, self._signed_in)

    def _signed_in(self, login: Login | None) -> None:
        if login is None:
            # Cancelling an added account leaves the current one; with nothing to fall back to, quit
            if not self.client.token:
                self.exit()
            return
        session = login.session
        account = Account(login.url, session.user.email)
        self.token_store.save(account, session.token)
        self._start_account(account, session.token)
        self.user = session.user
        self._signed_in_as(session.user)

    def _signed_in_as(self, user: User) -> None:
        self._go_online()
        self._show_account()
        self.query_one(YafsView).load()

    def _go_offline(self, detail: str) -> None:
        """Hide the list and everything that needs the server until a retry succeeds."""
        self._viewing = None
        self.query_one(YafDetail).hide()
        self.query_one(Echo).display = True
        self.query_one(YafsView).display = False
        self.query_one(OfflineNotice).show(server_name(self.url), detail)

    def _go_online(self) -> None:
        self.query_one(OfflineNotice).hide()
        self._show_list()

    def _show_list(self) -> None:
        self._viewing = None
        self.query_one(YafDetail).hide()
        self.query_one(Echo).display = True
        view = self.query_one(YafsView)
        view.display = True
        view.query_one(YafsTable).focus()

    def _show_yaf(self, yaf: Yaf) -> None:
        self._viewing = yaf
        self.query_one(YafsView).display = False
        self.query_one(Echo).display = False
        self.query_one(YafDetail).show(yaf)

    @on(ViewClosed)
    def _close_view(self) -> None:
        if self._viewing is not None:
            self._show_list()

    @on(RetryRequested)
    def _retry(self) -> None:
        self._check_token()

    def switch_account(self, account: Account) -> None:
        """Use another stored account, on whichever server it is; the settings screen and s are the ways in."""
        if account == self.account and self.client.token:
            return
        self.token_store.select(account)
        self._start_account(account, self.token_store.token(account))
        self._check_token()

    def action_next_account(self) -> None:
        """Move to the next stored account, wrapping around, so s alone cycles through them all."""
        accounts = self.token_store.accounts()
        if len(accounts) < 2:
            return
        index = accounts.index(self.account) if self.account in accounts else -1
        account = accounts[(index + 1) % len(accounts)]
        self.switch_account(account)
        self.notify(f"Switched to {account.label}")

    def add_account(self) -> None:
        """Log in to one more account; the current one stays stored."""
        self._ask_login(cancel_label="Cancel")

    def _start_account(self, account: Account | None, token: str) -> None:
        """Point the client at an account, and its server, and drop what was on screen for the last one."""
        self.account = account
        if account is not None:
            self.url = account.url
            self.servers = self.config.servers_with(self.url)
        self.client.base_url = self.url
        self.client.token = token
        self.user = None
        self.client.score = None
        self.query_one(Echo).sync()
        self.query_one(YafsView).reset()
        self._show_account()

    def _use_next_account(self, message: str) -> None:
        """After a token is gone, move to another stored account, or ask to log in."""
        accounts = self.token_store.accounts()
        if accounts:
            if message:
                self.notify(message, severity="warning")
            self.switch_account(self.token_store.current() or accounts[0])
        else:
            self._ask_login(message)

    def _show_account(self) -> None:
        email = self.account.email if self.account else ""
        # Only a non-production server is worth calling out
        server = server_name(self.url) if self.url != DEFAULT_URL else ""
        self.query_one(AppHeader).show_account(email, server)

    def confirm_sign_out(self) -> None:
        """Ask before signing out; the settings screen is the way in."""
        if not self.client.token:
            return
        who = self.account.label if self.account else self.url
        dialog = ConfirmDialog(
            f"You are signed in as {who}",
            title="Sign Out",
            confirm_label="Sign out",
            cancel_label="Cancel",
        )
        self.push_screen(dialog, lambda confirmed: self._sign_out() if confirmed else None)

    @work(exclusive=True)
    async def _sign_out(self) -> None:
        try:
            await asyncio.to_thread(self.client.logout)
        except (ApiError, ApiConnectionError):
            pass  # Forgetting the token locally is what signs out; revoking it is best effort
        self.token_store.clear(self.account)
        self._start_account(None, "")
        self._use_next_account("")

    @on(YafOpened)
    def _open_yaf(self, event: YafOpened) -> None:
        self._fetch_and_show(event.yaf)

    @on(EditRequested)
    def _edit_requested(self, event: EditRequested) -> None:
        self._fetch_and_edit(event.yaf)

    @work(exclusive=True, group="open")
    async def _fetch_and_show(self, yaf: Yaf) -> None:
        current = await self._fetch_current(yaf)
        if current is not None:
            self._show_yaf(current)

    @work(exclusive=True, group="open")
    async def _fetch_and_edit(self, yaf: Yaf) -> None:
        current = await self._fetch_current(yaf)
        if current is not None:
            # Suspend from a plain callback rather than inside this worker
            self.call_later(self._edit_yaf, current)

    async def _fetch_current(self, yaf: Yaf) -> Yaf | None:
        """The server's copy, so a yaf deleted or changed in the web app is not shown or edited stale."""
        view = self.query_one(YafsView)
        try:
            current = await asyncio.to_thread(self.client.get_yaf, yaf.id)
        except NotFoundError:
            self.notify("That yaf was deleted, refreshing the list", severity="warning")
            self._close_view()
            view.load()
            return None
        except (ApiError, ApiConnectionError) as error:
            self.notify(str(error), severity="error")
            return None
        view.replace(current)
        return current

    @on(NewYafRequested)
    def _new_yaf(self) -> None:
        self._edit_yaf(None)

    def _edit_yaf(self, yaf: Yaf | None) -> None:
        """Edit yaf in $VISUAL or $EDITOR, or write a new one when yaf is None."""
        if yaf is None:
            draft = Draft.create("", date.today(), "new")
        else:
            draft = Draft.create(yaf.content, yaf.date, yaf.id)
        self._edit_draft(yaf, draft)

    def _edit_draft(self, yaf: Yaf | None, draft: Draft) -> None:
        """Open the draft in the editor and save what comes back; a failed save offers the same draft again."""
        failure: Exception | None = None
        try:
            with self.suspend():
                try:
                    draft.edit()
                except EditorError as error:
                    # Textual only restores the TUI when the suspend block exits without raising
                    failure = error
        except SuspendNotSupported as error:
            failure = error
        if failure is not None:
            draft.discard()
            self.notify(str(failure), severity="error")
            return
        try:
            entry = draft.read()
        except DraftError as error:
            self._not_saved(yaf, draft, error)
            return
        blank = not entry.content.strip()
        # A new yaf left blank is a cancel, even if its date was changed
        if entry == draft.original or (yaf is None and blank):
            draft.discard()
        elif blank:
            # Blanking a yaf is how it gets deleted; the empty draft holds nothing worth keeping
            draft.discard()
            self._confirm_delete(yaf)
        else:
            self._save_yaf(yaf, draft, entry)

    def _confirm_delete(self, yaf: Yaf) -> None:
        dialog = ConfirmDialog(
            f"Delete the yaf from {yaf.date.isoformat()}?",
            title="Delete Yaf",
            confirm_label="Delete",
            cancel_label="Cancel",
            detail=yaf.summary,
        )
        self.push_screen(dialog, lambda confirmed: self._delete_yaf(yaf) if confirmed else None)

    @work(group="save")
    async def _delete_yaf(self, yaf: Yaf) -> None:
        try:
            await asyncio.to_thread(self.client.delete_yaf, yaf.id)
        except NotFoundError:
            pass  # Already deleted elsewhere, which is what was asked for
        except (ApiError, ApiConnectionError) as error:
            self.notify(f"Not deleted: {error}", severity="error")
            return
        self._close_view()
        self.query_one(YafsView).load()
        self.notify("Yaf deleted")

    @work(group="save")
    async def _save_yaf(self, yaf: Yaf | None, draft: Draft, entry: Entry) -> None:
        view = self.query_one(YafsView)
        message = "Yaf updated" if yaf is not None else "Yaf created"
        try:
            if yaf is not None:
                try:
                    saved = await asyncio.to_thread(self.client.update_yaf, yaf.id, entry.content, entry.date)
                except NotFoundError:
                    # Deleted elsewhere while the editor was open; keep the edit as a new yaf
                    yaf = None
                    message = "That yaf was deleted, saved your edit as a new yaf"
            if yaf is None:
                saved = await asyncio.to_thread(self.client.create_yaf, entry.content, entry.date)
        except (ApiError, ApiConnectionError) as error:
            self._not_saved(yaf, draft, error, entry=entry)
            return
        draft.discard()
        if yaf is None:
            # Where a new yaf lands depends on its date and the search, so let the server order it
            view.load()
        else:
            view.replace(saved)
        if self._viewing is not None:
            self._show_yaf(saved)
        self.notify(message)

    def _not_saved(self, yaf: Yaf | None, draft: Draft, error: Exception, entry: Entry | None = None) -> None:
        """Ask what to do with the edit; entry is what was parsed from the draft, when the server was the problem."""

        def chosen(choice: str) -> None:
            if choice == EDIT_AGAIN:
                # Suspend from a plain callback, once the dialog is gone
                self.call_later(self._edit_draft, yaf, draft)
            elif choice == RETRY and entry is not None:
                self._save_yaf(yaf, draft, entry)
            else:
                draft.discard()

        self.push_screen(NotSavedDialog(str(error), retry=entry is not None), chosen)

    @on(SettingsRequested)
    def action_settings(self) -> None:
        self.push_screen(SettingsScreen())
