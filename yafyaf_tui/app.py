import asyncio
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from textual import on, work
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.notifications import Notification, SeverityLevel

from .api import (
    ApiConnectionError,
    ApiError,
    AuthenticationError,
    NotFoundError,
    Session,
    User,
    Yaf,
    YafyafClient,
)
from .config import DEFAULT_URL, Config, TokenStore, load_config, save_theme
from .editor import Draft, DraftError, EditorError, Entry
from .screens import ConfirmDialog, LoginScreen, SettingsScreen, ThemePicker
from .shortcuts import GENERAL
from .theme import effective_theme, load_palette
from .widgets import (
    AccountLink,
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
        account: str = "",
    ) -> None:
        self.url = url
        self.config = config if config is not None else load_config()
        self.token_store = token_store if token_store is not None else TokenStore.for_url(url)
        # The email whose token is in use; "" until a legacy token (stored without one) is checked
        self.account = account or self.token_store.current()
        self.client = YafyafClient(url, self.token_store.load(self.account))
        self.user: User | None = None
        # The yaf shown in place of the list, if any; the editor returns there when it started there
        self._viewing: Yaf | None = None
        # The palette is served from get_css_variables rather than baked into
        # CSS, so apply_theme can swap it without restarting.
        self._palette = load_palette(self.config.theme)
        self.CSS = (STYLES_DIR / "base.tcss").read_text()
        super().__init__()

    def compose(self) -> ComposeResult:
        yield AppHeader(self.url)
        yield YafsView(self.client, **self._rich_colors())
        yield YafDetail()
        yield OfflineNotice(urlsplit(self.url).netloc)
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

        Markup is off by default because messages carry server errors and file paths, which may contain brackets.
        """
        notification = Notification(
            message,
            title,
            severity,
            self.NOTIFICATION_TIMEOUT if timeout is None else timeout,
            markup=markup,
        )
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
            markup=notification.markup,
        )

    def on_mount(self) -> None:
        for warning in self.config.warnings:
            self.notify(warning, severity="warning", timeout=10)
        self._show_account()
        if self.client.token:
            self._check_token()
        else:
            self._ask_login(email=self.account)

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
        # Files a legacy token under its email; for the others this rewrites the same file
        self.token_store.save(self.client.token, self.user.email)
        self.account = self.user.email
        self._signed_in_as(self.user)

    def _ask_login(self, message: str = "", email: str = "", cancel_label: str = "Quit") -> None:
        screen = LoginScreen(self.client, message, email=email, cancel_label=cancel_label)
        self.push_screen(screen, self._signed_in)

    def _signed_in(self, session: Session | None) -> None:
        if session is None:
            # Cancelling an added account leaves the current one; with nothing to fall back to, quit
            if not self.client.token:
                self.exit()
            return
        self.token_store.save(session.token, session.user.email)
        self._start_account(session.user.email, session.token)
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
        self.query_one(OfflineNotice).show(detail)

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

    def switch_account(self, account: str) -> None:
        """Use another stored account's token; the settings screen is the way in."""
        if account == self.account and self.client.token:
            return
        self.token_store.select(account)
        self._start_account(account, self.token_store.load(account))
        self._check_token()

    def action_next_account(self) -> None:
        """Move to the next stored account, wrapping around, so s alone cycles through them all."""
        accounts = self.token_store.accounts()
        if len(accounts) < 2:
            return
        index = accounts.index(self.account) if self.account in accounts else -1
        account = accounts[(index + 1) % len(accounts)]
        self.switch_account(account)
        self.notify(f"Switched to {account}")

    def add_account(self) -> None:
        """Log in to one more account; the current one stays stored."""
        self._ask_login(cancel_label="Cancel")

    def _start_account(self, account: str, token: str) -> None:
        """Point the client at an account and drop what was on screen for the last one."""
        self.account = account
        self.client.token = token
        self.user = None
        self.client.score = None
        self.query_one(Echo).sync()
        self.query_one(YafsView).reset()
        self._show_account()

    def _use_next_account(self, message: str) -> None:
        """After a token is gone, move to another stored account, or ask to log in."""
        if self.token_store.accounts():
            if message:
                self.notify(message, severity="warning")
            self.switch_account(self.token_store.current())
        else:
            self._ask_login(message)

    def _show_account(self) -> None:
        self.query_one(AccountLink).show(self.account)

    def confirm_sign_out(self) -> None:
        """Ask before signing out; the settings screen is the way in."""
        if not self.client.token:
            return
        who = self.user.email if self.user else self.account or self.url
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
        self._start_account("", "")
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
            self._not_saved(error, draft)
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
            self._not_saved(error, draft)
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

    def _not_saved(self, error: Exception, draft: Draft) -> None:
        # Keep the file so a failed save does not throw away the edit
        self.notify(
            f"Not saved: {error}\nEdit kept in {draft.path}",
            severity="error",
            timeout=30,
        )

    @on(SettingsRequested)
    def action_settings(self) -> None:
        self.push_screen(SettingsScreen())
