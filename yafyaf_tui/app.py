import asyncio
from datetime import date
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.notifications import Notification, SeverityLevel
from textual.widgets import Button, Static

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
from .theme import load_palette
from .widgets import AppHeader, HeaderNotification, NewYafRequested, YafOpened, YafsView

STYLES_DIR = Path(__file__).parent / "styles"


class YafyafApp(App):
    """Terminal client for the YafYaf notes API."""

    TITLE = "YafYaf"

    BINDINGS = [
        Binding("question_mark", "settings", "Settings", key_display="?", group=GENERAL),
        Binding("t", "show_themes", "Change theme", group=GENERAL),
        Binding("q", "quit", "Quit", group=GENERAL),
    ]

    def __init__(
        self,
        url: str = DEFAULT_URL,
        config: Config | None = None,
        token_store: TokenStore | None = None,
    ) -> None:
        self.url = url
        self.config = config if config is not None else load_config()
        self.token_store = token_store if token_store is not None else TokenStore.for_url(url)
        self.client = YafyafClient(url, self.token_store.load())
        self.user: User | None = None
        # The palette is served from get_css_variables rather than baked into
        # CSS, so apply_theme can swap it without restarting.
        self._palette = load_palette(self.config.theme)
        self.CSS = (STYLES_DIR / "base.tcss").read_text()
        super().__init__()

    def compose(self) -> ComposeResult:
        yield AppHeader(self.url)
        yield YafsView(self.client, **self._rich_colors())
        yield Static("", id="status-line")

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
        self.push_screen(ThemePicker(self.config.theme), callback=self._theme_chosen)

    def _theme_chosen(self, theme_name: str | None) -> None:
        if theme_name is not None:
            self.set_theme(theme_name)

    def set_theme(self, theme_name: str) -> None:
        """Apply a theme and remember it for next launch."""
        if theme_name == self.config.theme:
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
        if self.client.token:
            self._check_token()
        else:
            self._ask_login()

    @work(exclusive=True)
    async def _check_token(self) -> None:
        """Confirm the stored token still works before showing anything that needs it."""
        try:
            self.user = await asyncio.to_thread(self.client.me)
        except AuthenticationError:
            self.token_store.clear()
            self.client.token = ""
            self._ask_login("Your saved token was rejected; please log in again.")
            return
        except ApiConnectionError as error:
            self._set_status(str(error))
            return
        self._signed_in_as(self.user)

    def _ask_login(self, message: str = "") -> None:
        self.push_screen(LoginScreen(self.client, message), self._signed_in)

    def _signed_in(self, session: Session | None) -> None:
        if session is None:
            self.exit()
            return
        self.user = session.user
        self.client.token = session.token
        self.token_store.save(session.token)
        self._signed_in_as(session.user)

    def _signed_in_as(self, user: User) -> None:
        self._set_status("")
        self.query_one(YafsView).load()

    def confirm_sign_out(self) -> None:
        """Ask before signing out; the settings screen is the way in."""
        if not self.client.token:
            return
        who = self.user.email if self.user else self.url
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
        self.token_store.clear()
        self.client.token = ""
        self.user = None
        self.query_one(YafsView).reset()
        self._ask_login()

    def _set_status(self, text: str) -> None:
        status = self.query_one("#status-line", Static)
        status.update(text)
        # Only connection problems use this line now, so it takes no room otherwise
        status.display = bool(text)

    @on(YafOpened)
    def _open_yaf(self, event: YafOpened) -> None:
        self._fetch_and_edit(event.yaf)

    @work(exclusive=True, group="open")
    async def _fetch_and_edit(self, yaf: Yaf) -> None:
        """Edit the server's copy, so a yaf deleted or changed in the web app is not edited stale."""
        view = self.query_one(YafsView)
        try:
            current = await asyncio.to_thread(self.client.get_yaf, yaf.id)
        except NotFoundError:
            self.notify("That yaf was deleted, refreshing the list", severity="warning")
            view.load()
            return
        except (ApiError, ApiConnectionError) as error:
            self.notify(str(error), severity="error")
            return
        view.replace(current)
        # Suspend from a plain callback rather than inside this worker
        self.call_later(self._edit_yaf, current)

    @on(NewYafRequested)
    def _new_yaf(self) -> None:
        self._edit_yaf(None)

    def _edit_yaf(self, yaf: Yaf | None) -> None:
        """Edit yaf in $EDITOR, or write a new one when yaf is None."""
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
                await asyncio.to_thread(self.client.create_yaf, entry.content, entry.date)
        except (ApiError, ApiConnectionError) as error:
            self._not_saved(error, draft)
            return
        draft.discard()
        if yaf is None:
            # Where a new yaf lands depends on its date and the search, so let the server order it
            view.load()
        else:
            view.replace(saved)
        self.notify(message)

    def _not_saved(self, error: Exception, draft: Draft) -> None:
        # Keep the file so a failed save does not throw away the edit
        self.notify(
            f"Not saved: {error}\nEdit kept in {draft.path}",
            severity="error",
            timeout=30,
        )

    @on(Button.Pressed, "#btn-settings")
    def action_settings(self) -> None:
        self.push_screen(SettingsScreen())
