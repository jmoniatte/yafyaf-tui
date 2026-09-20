"""How the app opens, edits, saves and deletes yafs through the external editor; mixed into YafyafApp.

Message handlers stay on the app class, since Textual only registers them there; this holds the
work they delegate to.
"""

import asyncio
from datetime import date

from textual import work
from textual.app import SuspendNotSupported

from .api import ApiConnectionError, ApiError, NotFoundError, Yaf, YafyafClient
from .editor import Draft, DraftError, EditorError, Entry
from .screens import EDIT_AGAIN, RETRY, ConfirmDialog, NotSavedDialog
from .widgets import MainArea, YafsView


class EditFlow:
    # Set by YafyafApp, which this mixes into
    client: YafyafClient
    main: MainArea

    @work(exclusive=True, group="open")
    async def _fetch_and_show(self, yaf: Yaf) -> None:
        current = await self._fetch_current(yaf)
        if current is not None:
            self.main.show_yaf(current)

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
        if self.main.viewing is not None:
            self.main.show_yaf(saved)
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
